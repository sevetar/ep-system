from types import SimpleNamespace

from flowfix_agent.dispatch.domain.models import DispatchTrigger
from flowfix_agent.dispatch.runtime.models import RuntimeStatus
from flowfix_agent.messaging.models import DispatchEvent
from flowfix_agent.messaging.rabbitmq import RabbitDispatchBridge


class FakeLease:
    def __init__(self, token="token"):
        self.token = token
        self.released = []

    async def acquire(self, resource, ttl_seconds):
        return self.token

    async def release(self, resource, token):
        self.released.append((resource, token))
        return True


class FakeRuntime:
    def __init__(self):
        self.inputs = []

    async def start(self, runtime_input):
        self.inputs.append(runtime_input)
        return SimpleNamespace(
            thread_id="tenant-1:dispatch-1",
            status=RuntimeStatus.AUDITED,
            interrupted=False,
            errors=[],
            assignment_outcome=None,
        )


class FakeMessage:
    def __init__(self, body: bytes, headers=None):
        self.body = body
        self.headers = headers or {}
        self.acked = False

    async def ack(self):
        self.acked = True


class CapturingBridge(RabbitDispatchBridge):
    def __init__(self, runtime, lease):
        super().__init__(
            "amqp://unused", runtime, lease, instance_id="test-instance"
        )
        self.published = []

    async def _publish(self, body, routing_key, **kwargs):
        self.published.append((routing_key, body, kwargs))


def _event() -> DispatchEvent:
    return DispatchEvent(
        event_id="event-1",
        dispatch_id="dispatch-1",
        tenant_id="tenant-1",
        work_order_id="wo-1",
        trace_id="trace-1",
    )


async def test_rabbit_consumer_runs_dispatch_publishes_outcome_then_acks():
    runtime = FakeRuntime()
    lease = FakeLease()
    bridge = CapturingBridge(runtime, lease)
    message = FakeMessage(_event().model_dump_json().encode())

    await bridge._on_message(message)

    assert message.acked is True
    assert runtime.inputs[0].request.event_id == "event-1"
    assert bridge.published[0][0] == bridge.topology.outcome_key
    assert lease.released == [("dispatch-event:tenant-1:event-1", "token")]


async def test_rabbit_consumer_retries_without_executing_when_lease_is_busy():
    runtime = FakeRuntime()
    bridge = CapturingBridge(runtime, FakeLease(token=None))
    message = FakeMessage(_event().model_dump_json().encode())

    await bridge._on_message(message)

    assert message.acked is True
    assert runtime.inputs == []
    routing_key, _, headers = bridge.published[0]
    assert routing_key == bridge.topology.retry_key
    assert headers["headers"]["x-retry-count"] == 0


async def test_rabbit_contract_accepts_all_supported_dispatch_triggers():
    for trigger in DispatchTrigger:
        runtime = FakeRuntime()
        bridge = CapturingBridge(runtime, FakeLease())
        event = _event().model_copy(update={"trigger": trigger})

        await bridge._on_message(FakeMessage(event.model_dump_json().encode()))

        assert runtime.inputs[0].request.trigger == trigger
