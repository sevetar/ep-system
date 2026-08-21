from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import aio_pika
from aio_pika import DeliveryMode, ExchangeType, IncomingMessage, Message
from pydantic import ValidationError

from flowfix_agent.dispatch.domain.models import DispatchRequest
from flowfix_agent.dispatch.runtime.models import DispatchRuntimeInput, RequestContext
from flowfix_agent.messaging.models import DispatchEvent, DispatchOutcomeEvent
from flowfix_agent.reliability import RedisLeaseManager

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RabbitTopology:
    exchange: str = "flowfix.agent"
    request_queue: str = "flowfix.agent.dispatch.requests"
    retry_queue: str = "flowfix.agent.dispatch.requests.retry"
    dead_letter_queue: str = "flowfix.agent.dispatch.requests.dlq"
    request_key: str = "flowfix.dispatch.requested.v1"
    retry_key: str = "flowfix.dispatch.requested.retry.v1"
    dead_letter_key: str = "flowfix.dispatch.requested.dead.v1"
    outcome_key: str = "flowfix.dispatch.outcome.v1"


class RabbitDispatchBridge:
    """可靠派单事件消费者：confirm publish、手动 ACK、定时重试、DLQ 与 Redis 租约。"""

    def __init__(
        self,
        url: str,
        runtime: Any,
        lease_manager: RedisLeaseManager,
        *,
        instance_id: str,
        topology: RabbitTopology | None = None,
        retry_delay_ms: int = 5000,
        max_retries: int = 3,
        approval_ttl_seconds: int = 3600,
    ) -> None:
        self.url = url
        self.runtime = runtime
        self.leases = lease_manager
        self.instance_id = instance_id
        self.topology = topology or RabbitTopology()
        self.retry_delay_ms = retry_delay_ms
        self.max_retries = max_retries
        self.approval_ttl_seconds = approval_ttl_seconds
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
        await self._request_queue.bind(self.exchange, self.topology.request_key)
        await retry_queue.bind(self.exchange, self.topology.retry_key)
        await dead_queue.bind(self.exchange, self.topology.dead_letter_key)
        self._consumer_tag = await self._request_queue.consume(
            self._on_message,
            consumer_tag=f"flowfix-{self.instance_id}",
        )

    async def close(self) -> None:
        if self._request_queue is not None and self._consumer_tag is not None:
            await self._request_queue.cancel(self._consumer_tag)
        if self.connection is not None and not self.connection.is_closed:
            await self.connection.close()

    async def health(self) -> bool:
        return bool(self.connection and not self.connection.is_closed)

    async def publish_request(self, event: DispatchEvent) -> None:
        await self._publish(
            event.model_dump_json().encode(),
            self.topology.request_key,
            message_id=event.event_id,
        )

    async def _on_message(self, message: IncomingMessage) -> None:
        retry_count = int((message.headers or {}).get("x-retry-count", 0))
        try:
            event = DispatchEvent.model_validate_json(message.body)
        except ValidationError as exc:
            await self._publish_dead(message.body, retry_count, f"invalid_event:{exc}")
            await message.ack()
            return

        resource = f"dispatch-event:{event.tenant_id}:{event.event_id}"
        token = await self.leases.acquire(resource, event.deadline_seconds + 30)
        if token is None:
            await self._publish_retry(message.body, retry_count, "lease_busy", increment=False)
            await message.ack()
            return
        try:
            result = await self.runtime.start(self._runtime_input(event))
            outcome = DispatchOutcomeEvent(
                event_id=event.event_id,
                dispatch_id=event.dispatch_id,
                tenant_id=event.tenant_id,
                trace_id=event.trace_id,
                thread_id=result.thread_id,
                status=result.status.value,
                interrupted=result.interrupted,
                errors=result.errors,
                assignment_outcome=(
                    result.assignment_outcome.model_dump(mode="json")
                    if result.assignment_outcome
                    else None
                ),
            )
            await self._publish(
                outcome.model_dump_json().encode(),
                self.topology.outcome_key,
                message_id=f"outcome:{event.event_id}",
            )
            await message.ack()
        except Exception as exc:
            logger.exception("Rabbit dispatch event failed: %s", event.event_id)
            if retry_count < self.max_retries:
                await self._publish_retry(
                    message.body, retry_count, type(exc).__name__, increment=True
                )
            else:
                await self._publish_dead(
                    message.body, retry_count, f"retries_exhausted:{type(exc).__name__}"
                )
            await message.ack()
        finally:
            await self.leases.release(resource, token)

    def _runtime_input(self, event: DispatchEvent) -> DispatchRuntimeInput:
        now = datetime.now(UTC)
        return DispatchRuntimeInput(
            request=DispatchRequest(
                dispatch_id=event.dispatch_id,
                event_id=event.event_id,
                tenant_id=event.tenant_id,
                trigger=event.trigger,
                requested_at=event.occurred_at,
            ),
            work_order_id=event.work_order_id,
            context=RequestContext(
                trace_id=event.trace_id,
                tenant_id=event.tenant_id,
                event_id=event.event_id,
                permissions=["dispatch:read", "dispatch:write", "dispatch:audit"],
                deadline=now + timedelta(seconds=event.deadline_seconds),
                approval_expires_at=now + timedelta(seconds=self.approval_ttl_seconds),
                execution_timeout_seconds=event.deadline_seconds,
            ),
        )

    async def _publish_retry(
        self, body: bytes, retry_count: int, error: str, *, increment: bool
    ) -> None:
        next_count = retry_count + 1 if increment else retry_count
        await self._publish(
            body,
            self.topology.retry_key,
            headers={"x-retry-count": next_count, "x-last-error": error},
        )

    async def _publish_dead(self, body: bytes, retry_count: int, error: str) -> None:
        await self._publish(
            body,
            self.topology.dead_letter_key,
            headers={"x-retry-count": retry_count, "x-dead-reason": error[:500]},
        )

    async def _publish(
        self,
        body: bytes,
        routing_key: str,
        *,
        message_id: str | None = None,
        headers: dict[str, Any] | None = None,
    ) -> None:
        if self.exchange is None:
            raise RuntimeError("RabbitMQ bridge is not started")
        await self.exchange.publish(
            Message(
                body=body,
                delivery_mode=DeliveryMode.PERSISTENT,
                content_type="application/json",
                message_id=message_id,
                headers=headers or {},
            ),
            routing_key=routing_key,
            mandatory=True,
        )
