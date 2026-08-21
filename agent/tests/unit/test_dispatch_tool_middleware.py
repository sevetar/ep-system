import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from flowfix_agent.core.errors import DependencyUnavailableError
from flowfix_agent.dispatch.adapters.fake_tools import FakeDispatchToolAdapter
from flowfix_agent.dispatch.domain.models import WorkerSnapshot, WorkOrderSnapshot
from flowfix_agent.dispatch.runtime.errors import (
    ToolAccessDeniedError,
    ToolCircuitOpenError,
    ToolDeadlineExceededError,
    ToolRateLimitError,
)
from flowfix_agent.dispatch.runtime.middleware import DispatchToolGateway
from flowfix_agent.dispatch.runtime.models import (
    AssignmentCommand,
    AssignmentReceiptStatus,
    RequestContext,
    ToolName,
)
from flowfix_agent.dispatch.skills.loader import DispatchSkillLoader

BUILTIN = Path("src/flowfix_agent/dispatch/skills/builtin")
NOW = datetime(2026, 8, 4, 8, 0, tzinfo=UTC)


# 模拟业务写入已提交但首次响应丢失的工具适配器。
class CommitThenLoseResponseAdapter(FakeDispatchToolAdapter):
    # 初始化首次响应丢失标志。
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.lose_once = True

    # 首次完成真实写入后抛出依赖错误，后续调用返回幂等结果。
    async def create_assignment(self, command, context):
        receipt = await super().create_assignment(command, context)
        if self.lose_once:
            self.lose_once = False
            raise DependencyUnavailableError("response_lost_after_commit")
        return receipt


# 模拟读取工单快照持续超时的工具适配器。
class SlowSnapshotAdapter(FakeDispatchToolAdapter):
    # 延迟返回工单快照以触发网关超时控制。
    async def get_work_order_snapshot(self, work_order_id, context):
        await asyncio.sleep(0.02)
        return await super().get_work_order_snapshot(work_order_id, context)


# 构造工具中间件测试使用的待派单工单。
def make_order() -> WorkOrderSnapshot:
    return WorkOrderSnapshot(
        work_order_id="wo-1",
        tenant_id="tenant-1",
        device_id="device-1",
        region="east",
        required_skills=["plc"],
        version=3,
        captured_at=NOW,
    )


# 构造工具中间件测试使用的合格工作人员。
def make_worker() -> WorkerSnapshot:
    return WorkerSnapshot(
        worker_id="worker-1",
        tenant_id="tenant-1",
        region="east",
        skills={"plc": 1.0},
        current_load=0,
        capacity=5,
        distance_km=1,
        sla_readiness=1.0,
        captured_at=NOW,
    )


# 构造包含完整权限、预算和截止时间的请求上下文。
def make_context(**updates) -> RequestContext:
    data = {
        "trace_id": "trace-1",
        "tenant_id": "tenant-1",
        "event_id": "event-1",
        "permissions": ["dispatch:read", "dispatch:write", "dispatch:audit"],
        "deadline": datetime.now(UTC) + timedelta(minutes=1),
    }
    return RequestContext(**(data | updates))


# 构造带事件血缘、期望版本和幂等键的派单命令。
def make_command() -> AssignmentCommand:
    return AssignmentCommand(
        tenant_id="tenant-1",
        event_id="event-1",
        dispatch_id="dispatch-1",
        work_order_id="wo-1",
        worker_id="worker-1",
        expected_version=3,
        idempotency_key="assignment:tenant-1:event-1:wo-1:v3",
    )


# 验证可重试依赖故障不会产生重复写入且每次尝试均被审计。
async def test_write_retry_is_idempotent_and_audited() -> None:
    adapter = FakeDispatchToolAdapter([make_order()], [make_worker()])
    adapter.fail_next(ToolName.CREATE_ASSIGNMENT)
    gateway = DispatchToolGateway(adapter, max_attempts=2)
    skill = DispatchSkillLoader().load(BUILTIN / "balanced-v1.json")

    receipt = await gateway.create_assignment(make_command(), make_context(), skill)

    assert receipt.status == AssignmentReceiptStatus.ACCEPTED
    assert adapter.call_counts[ToolName.CREATE_ASSIGNMENT.value] == 2
    assert adapter.side_effect_counts[ToolName.CREATE_ASSIGNMENT.value] == 1
    assert [event.success for event in gateway.audit_events] == [False, True]


# 验证提交后响应丢失的重试不会重复产生业务副作用。
async def test_lost_response_after_commit_retries_without_duplicate_side_effect() -> None:
    adapter = CommitThenLoseResponseAdapter([make_order()], [make_worker()])
    gateway = DispatchToolGateway(adapter, max_attempts=2)
    skill = DispatchSkillLoader().load(BUILTIN / "balanced-v1.json")

    receipt = await gateway.create_assignment(make_command(), make_context(), skill)

    assert receipt.status == AssignmentReceiptStatus.ALREADY_APPLIED
    assert adapter.call_counts[ToolName.CREATE_ASSIGNMENT.value] == 2
    assert adapter.side_effect_counts[ToolName.CREATE_ASSIGNMENT.value] == 1


# 验证请求缺少权限时在调用底层适配器前即被拒绝。
async def test_missing_request_permission_denies_tool_before_adapter_call() -> None:
    adapter = FakeDispatchToolAdapter([make_order()], [make_worker()])
    gateway = DispatchToolGateway(adapter)
    skill = DispatchSkillLoader().load(BUILTIN / "balanced-v1.json")

    with pytest.raises(ToolAccessDeniedError, match="dispatch:write"):
        await gateway.create_assignment(
            make_command(), make_context(permissions=["dispatch:read"]), skill
        )
    assert adapter.call_counts[ToolName.CREATE_ASSIGNMENT.value] == 0


# 验证 Skill 声明不能扩展系统级工具白名单。
async def test_skill_cannot_expand_system_allowlist() -> None:
    adapter = FakeDispatchToolAdapter([make_order()], [make_worker()])
    gateway = DispatchToolGateway(
        adapter, system_allowlist={ToolName.GET_WORK_ORDER_SNAPSHOT}
    )
    skill = DispatchSkillLoader().load(BUILTIN / "balanced-v1.json")

    with pytest.raises(ToolAccessDeniedError, match="system allowlist"):
        await gateway.create_assignment(make_command(), make_context(), skill)


# 验证超过截止时间的请求不会调用底层工具。
async def test_expired_deadline_fails_before_tool_call() -> None:
    adapter = FakeDispatchToolAdapter([make_order()], [make_worker()])
    gateway = DispatchToolGateway(adapter)
    skill = DispatchSkillLoader().load(BUILTIN / "balanced-v1.json")

    with pytest.raises(ToolDeadlineExceededError):
        await gateway.get_work_order_snapshot(
            "wo-1",
            make_context(deadline=datetime.now(UTC) - timedelta(seconds=1)),
            skill,
        )
    assert adapter.call_counts[ToolName.GET_WORK_ORDER_SNAPSHOT.value] == 0


# 验证工具审计会递归遮蔽嵌套载荷中的敏感字段。
async def test_tool_audit_redacts_nested_secrets() -> None:
    adapter = FakeDispatchToolAdapter([make_order()], [make_worker()])
    gateway = DispatchToolGateway(adapter)
    skill = DispatchSkillLoader().load(BUILTIN / "balanced-v1.json")

    await gateway.publish_dispatch_audit(
        "dispatch-1",
        {"token": "do-not-log", "nested": {"password": "hidden"}},
        make_context(),
        skill,
    )

    payload = gateway.audit_events[-1].request["payload"]
    assert payload["token"] == "[REDACTED]"
    assert payload["nested"]["password"] == "[REDACTED]"


# 验证期望版本冲突返回明确回执且不产生业务副作用。
async def test_expected_version_conflict_has_no_business_side_effect() -> None:
    adapter = FakeDispatchToolAdapter([make_order()], [make_worker()])
    gateway = DispatchToolGateway(adapter)
    skill = DispatchSkillLoader().load(BUILTIN / "balanced-v1.json")
    command = make_command().model_copy(update={"expected_version": 2})

    receipt = await gateway.create_assignment(command, make_context(), skill)

    assert receipt.status == AssignmentReceiptStatus.VERSION_CONFLICT
    assert adapter.side_effect_counts[ToolName.CREATE_ASSIGNMENT.value] == 0


# 验证同一幂等键不能用于内容不同的派单命令。
async def test_same_idempotency_key_rejects_different_command() -> None:
    adapter = FakeDispatchToolAdapter([make_order()], [make_worker()])
    gateway = DispatchToolGateway(adapter)
    skill = DispatchSkillLoader().load(BUILTIN / "balanced-v1.json")
    context = make_context()
    first = await gateway.create_assignment(make_command(), context, skill)
    changed = make_command().model_copy(update={"worker_id": "worker-other"})

    second = await gateway.create_assignment(changed, context, skill)

    assert first.status == AssignmentReceiptStatus.ACCEPTED
    assert second.status == AssignmentReceiptStatus.REJECTED
    assert second.message == "idempotency_key_reused_with_different_command"
    assert adapter.side_effect_counts[ToolName.CREATE_ASSIGNMENT.value] == 1


# 验证工具调用预算耗尽后提供确定性的背压保护。
async def test_tool_call_budget_provides_backpressure() -> None:
    adapter = FakeDispatchToolAdapter([make_order()], [make_worker()])
    gateway = DispatchToolGateway(adapter)
    skill = DispatchSkillLoader().load(BUILTIN / "balanced-v1.json")
    context = make_context(max_tool_calls=1)
    await gateway.get_work_order_snapshot("wo-1", context, skill)

    with pytest.raises(ToolRateLimitError):
        await gateway.get_work_order_snapshot("wo-1", context, skill)


# 验证慢工具调用受超时和有限重试约束。
async def test_slow_tool_is_bounded_by_timeout() -> None:
    adapter = SlowSnapshotAdapter([make_order()], [make_worker()])
    gateway = DispatchToolGateway(adapter, timeout_seconds=0.001, max_attempts=1)
    skill = DispatchSkillLoader().load(BUILTIN / "balanced-v1.json")

    with pytest.raises(ToolDeadlineExceededError, match="tool timeout"):
        await gateway.get_work_order_snapshot("wo-1", make_context(), skill)


# 验证连续依赖故障达到阈值后工具进入熔断状态。
async def test_repeated_dependency_failures_open_circuit() -> None:
    adapter = FakeDispatchToolAdapter([make_order()], [make_worker()])
    adapter.fail_next(ToolName.GET_WORK_ORDER_SNAPSHOT, times=3)
    gateway = DispatchToolGateway(
        adapter, max_attempts=1, circuit_failure_threshold=2
    )
    skill = DispatchSkillLoader().load(BUILTIN / "balanced-v1.json")
    context = make_context()

    with pytest.raises(DependencyUnavailableError):
        await gateway.get_work_order_snapshot("wo-1", context, skill)
    with pytest.raises(DependencyUnavailableError):
        await gateway.get_work_order_snapshot("wo-1", context, skill)
    with pytest.raises(ToolCircuitOpenError):
        await gateway.get_work_order_snapshot("wo-1", context, skill)
    assert adapter.call_counts[ToolName.GET_WORK_ORDER_SNAPSHOT.value] == 2
