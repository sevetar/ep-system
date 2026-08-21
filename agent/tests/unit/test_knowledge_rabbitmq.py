from datetime import UTC, datetime

from flowfix_agent.knowledge.models import (
    WorkOrderKnowledgeIngestionResult,
    WorkOrderKnowledgeStatus,
)
from flowfix_agent.messaging.knowledge_rabbitmq import RabbitWorkOrderKnowledgeBridge
from flowfix_agent.messaging.models import WorkOrderCompletedEvent


class FakeLease:
    def __init__(self, token="token"):
        self.token = token
        self.released = []

    async def acquire(self, resource, ttl_seconds):
        return self.token

    async def release(self, resource, token):
        self.released.append((resource, token))
        return True


class FakeIngestion:
    def __init__(self, status="indexed"):
        self.status = status
        self.events = []

    async def ingest(self, event):
        self.events.append(event)
        return WorkOrderKnowledgeIngestionResult(
            event_id=event.event_id,
            tenant_id=event.tenant_id,
            work_order_id=event.work_order_id,
            source_id=f"work-order/{event.tenant_id}/{event.work_order_id}",
            version="v2-test",
            status=WorkOrderKnowledgeStatus(self.status),
            chunks=2,
            quality_score=90,
            error="provider unavailable" if self.status == "failed" else None,
        )


class FakeMessage:
    def __init__(self, body, headers=None):
        self.body = body
        self.headers = headers or {}
        self.acked = False

    async def ack(self):
        self.acked = True


class CapturingBridge(RabbitWorkOrderKnowledgeBridge):
    def __init__(self, ingestion, lease, max_retries=3):
        super().__init__(
            "amqp://unused",
            ingestion,
            lease,
            instance_id="test",
            max_retries=max_retries,
        )
        self.published = []

    async def _publish(self, body, routing_key, **kwargs):
        self.published.append((routing_key, body, kwargs))


def _event():
    return WorkOrderCompletedEvent(
        event_id="event-1",
        tenant_id="tenant-1",
        work_order_id="1",
        work_order_version=2,
        device_id="9",
        description="故障",
        repair_process="处理",
        solution="修复",
        verification_result="运行正常",
        completed_at=datetime.now(UTC),
        trace_id="trace-1",
    )


async def test_knowledge_consumer_ingests_and_acks():
    ingestion = FakeIngestion()
    lease = FakeLease()
    bridge = CapturingBridge(ingestion, lease)
    message = FakeMessage(_event().model_dump_json().encode())

    await bridge._on_message(message)

    assert message.acked is True
    assert ingestion.events[0].tenant_id == "tenant-1"
    assert bridge.published[0][0] == bridge.topology.result_key
    assert lease.released == [("knowledge-event:tenant-1:event-1", "token")]


async def test_knowledge_consumer_retries_failed_ingestion():
    bridge = CapturingBridge(FakeIngestion(status="failed"), FakeLease())
    message = FakeMessage(_event().model_dump_json().encode())

    await bridge._on_message(message)

    assert message.acked is True
    routing_key, _, kwargs = bridge.published[0]
    assert routing_key == bridge.topology.retry_key
    assert kwargs["headers"]["x-retry-count"] == 1


async def test_knowledge_consumer_sends_invalid_contract_to_dlq():
    bridge = CapturingBridge(FakeIngestion(), FakeLease())
    message = FakeMessage(b'{"event_id":"broken"}')

    await bridge._on_message(message)

    assert message.acked is True
    assert bridge.published[0][0] == bridge.topology.dead_letter_key
