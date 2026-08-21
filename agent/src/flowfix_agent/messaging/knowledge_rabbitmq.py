from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import aio_pika
from aio_pika import DeliveryMode, ExchangeType, IncomingMessage, Message
from pydantic import ValidationError

from flowfix_agent.knowledge.models import WorkOrderKnowledgeStatus
from flowfix_agent.knowledge.work_order import WorkOrderCaseIngestionService
from flowfix_agent.messaging.models import (
    WorkOrderCompletedEvent,
    WorkOrderKnowledgeOutcomeEvent,
)
from flowfix_agent.reliability import RedisLeaseManager

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class KnowledgeRabbitTopology:
    exchange: str = "flowfix.agent"
    request_queue: str = "flowfix.agent.knowledge.work-orders"
    retry_queue: str = "flowfix.agent.knowledge.work-orders.retry"
    dead_letter_queue: str = "flowfix.agent.knowledge.work-orders.dlq"
    result_queue: str = "flowfix.java.knowledge.ingestion-results"
    request_key: str = "flowfix.knowledge.work-order-completed.v1"
    retry_key: str = "flowfix.knowledge.work-order-completed.retry.v1"
    dead_letter_key: str = "flowfix.knowledge.work-order-completed.dead.v1"
    result_key: str = "flowfix.knowledge.ingestion-result.v1"


class RabbitWorkOrderKnowledgeBridge:
    """可靠消费工单完成事件，并将成功案例写入知识检索投影。"""

    def __init__(
        self,
        url: str,
        ingestion: WorkOrderCaseIngestionService,
        lease_manager: RedisLeaseManager,
        *,
        instance_id: str,
        topology: KnowledgeRabbitTopology | None = None,
        retry_delay_ms: int = 5000,
        max_retries: int = 3,
        lease_ttl_seconds: int = 300,
    ) -> None:
        self.url = url
        self.ingestion = ingestion
        self.leases = lease_manager
        self.instance_id = instance_id
        self.topology = topology or KnowledgeRabbitTopology()
        self.retry_delay_ms = retry_delay_ms
        self.max_retries = max_retries
        self.lease_ttl_seconds = lease_ttl_seconds
        self.connection: aio_pika.abc.AbstractRobustConnection | None = None
        self.channel: aio_pika.abc.AbstractRobustChannel | None = None
        self.exchange: aio_pika.abc.AbstractRobustExchange | None = None
        self._request_queue: aio_pika.abc.AbstractRobustQueue | None = None
        self._consumer_tag: str | None = None

    async def start(self) -> None:
        self.connection = await aio_pika.connect_robust(self.url)
        self.channel = await self.connection.channel(publisher_confirms=True)
        await self.channel.set_qos(prefetch_count=1)
        self.exchange = await self.channel.declare_exchange(
            self.topology.exchange, ExchangeType.DIRECT, durable=True
        )
        self._request_queue = await self.channel.declare_queue(
            self.topology.request_queue, durable=True
        )
        retry_queue = await self.channel.declare_queue(
            self.topology.retry_queue,
            durable=True,
            arguments={
                "x-message-ttl": self.retry_delay_ms,
                "x-dead-letter-exchange": self.topology.exchange,
                "x-dead-letter-routing-key": self.topology.request_key,
            },
        )
        dead_queue = await self.channel.declare_queue(
            self.topology.dead_letter_queue, durable=True
        )
        result_queue = await self.channel.declare_queue(
            self.topology.result_queue, durable=True
        )
        await self._request_queue.bind(self.exchange, self.topology.request_key)
        await retry_queue.bind(self.exchange, self.topology.retry_key)
        await dead_queue.bind(self.exchange, self.topology.dead_letter_key)
        await result_queue.bind(self.exchange, self.topology.result_key)
        self._consumer_tag = await self._request_queue.consume(
            self._on_message,
            consumer_tag=f"flowfix-knowledge-{self.instance_id}",
        )

    async def close(self) -> None:
        if self._request_queue is not None and self._consumer_tag is not None:
            await self._request_queue.cancel(self._consumer_tag)
        if self.connection is not None and not self.connection.is_closed:
            await self.connection.close()

    async def health(self) -> bool:
        return bool(self.connection and not self.connection.is_closed)

    async def _on_message(self, message: IncomingMessage) -> None:
        retry_count = int((message.headers or {}).get("x-retry-count", 0))
        try:
            event = WorkOrderCompletedEvent.model_validate_json(message.body)
        except ValidationError as exc:
            await self._publish_dead(message.body, retry_count, f"invalid_event:{exc}")
            await message.ack()
            return

        resource = f"knowledge-event:{event.tenant_id}:{event.event_id}"
        token = await self.leases.acquire(resource, self.lease_ttl_seconds)
        if token is None:
            await self._publish_retry(message.body, retry_count, "lease_busy", increment=False)
            await message.ack()
            return
        try:
            result = await self.ingestion.ingest(event)
            if result.status == WorkOrderKnowledgeStatus.FAILED:
                raise RuntimeError(result.error or "knowledge ingestion failed")
            await self._publish_outcome(event, result)
            await message.ack()
        except Exception as exc:
            logger.exception("Work-order knowledge event failed: %s", event.event_id)
            if retry_count < self.max_retries:
                await self._publish_retry(
                    message.body, retry_count, type(exc).__name__, increment=True
                )
            else:
                await self._publish_failed_outcome(event, type(exc).__name__)
                await self._publish_dead(
                    message.body, retry_count, f"retries_exhausted:{type(exc).__name__}"
                )
            await message.ack()
        finally:
            await self.leases.release(resource, token)

    async def _publish_retry(
        self, body: bytes, retry_count: int, error: str, *, increment: bool
    ) -> None:
        await self._publish(
            body,
            self.topology.retry_key,
            headers={
                "x-retry-count": retry_count + 1 if increment else retry_count,
                "x-last-error": error,
            },
        )

    async def _publish_dead(self, body: bytes, retry_count: int, error: str) -> None:
        await self._publish(
            body,
            self.topology.dead_letter_key,
            headers={"x-retry-count": retry_count, "x-dead-reason": error[:500]},
        )

    async def _publish_outcome(self, event: WorkOrderCompletedEvent, result: Any) -> None:
        outcome = WorkOrderKnowledgeOutcomeEvent(
            event_id=event.event_id,
            tenant_id=event.tenant_id,
            work_order_id=event.work_order_id,
            source_id=result.source_id,
            source_version=result.version,
            status=result.status.value,
            chunks=result.chunks,
            quality_score=result.quality_score,
            quality_issues=result.quality_issues,
            error=result.error,
        )
        await self._publish(outcome.model_dump_json().encode(), self.topology.result_key)

    async def _publish_failed_outcome(
        self, event: WorkOrderCompletedEvent, error_type: str
    ) -> None:
        outcome = WorkOrderKnowledgeOutcomeEvent(
            event_id=event.event_id,
            tenant_id=event.tenant_id,
            work_order_id=event.work_order_id,
            source_id=WorkOrderCaseIngestionService.source_id(
                event.tenant_id, event.work_order_id
            ),
            source_version=f"v{event.work_order_version}-failed",
            status=WorkOrderKnowledgeStatus.FAILED.value,
            error=f"retries_exhausted:{error_type}",
        )
        await self._publish(outcome.model_dump_json().encode(), self.topology.result_key)

    async def _publish(
        self,
        body: bytes,
        routing_key: str,
        *,
        headers: dict[str, Any] | None = None,
    ) -> None:
        if self.exchange is None:
            raise RuntimeError("RabbitMQ bridge is not started")
        await self.exchange.publish(
            Message(
                body=body,
                delivery_mode=DeliveryMode.PERSISTENT,
                content_type="application/json",
                headers=headers or {},
            ),
            routing_key=routing_key,
            mandatory=True,
        )
