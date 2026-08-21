import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from flowfix_agent.core.errors import DependencyUnavailableError
from flowfix_agent.dispatch.adapters.decision_repository import InMemoryDispatchDecisionRepository
from flowfix_agent.dispatch.adapters.fake_tools import FakeDispatchToolAdapter
from flowfix_agent.dispatch.adapters.skill_registry import FileDispatchSkillRegistry
from flowfix_agent.dispatch.application.service import DispatchDecisionService
from flowfix_agent.dispatch.domain.models import (
    DispatchRequest,
    WorkerSnapshot,
    WorkOrderPriority,
    WorkOrderSnapshot,
)
from flowfix_agent.dispatch.runtime.errors import (
    ApprovalValidationError,
    ToolAccessDeniedError,
)
from flowfix_agent.dispatch.runtime.graph import DispatchAgentRuntime
from flowfix_agent.dispatch.runtime.middleware import DispatchToolGateway
from flowfix_agent.dispatch.runtime.models import (
    ApprovalDecision,
    DispatchRuntimeInput,
    RequestContext,
    RuntimeResult,
    RuntimeStatus,
    ToolName,
)
from flowfix_agent.dispatch.skills.loader import DispatchSkillLoader
from flowfix_agent.dispatch.skills.manifest import DispatchSkill

BUILTIN = Path("src/flowfix_agent/dispatch/skills/builtin")
NOW = datetime(2026, 8, 4, 8, 0, tzinfo=UTC)


# 构造可按字段覆盖的待派单工单快照。
def make_order(**updates) -> WorkOrderSnapshot:
    data = {
        "work_order_id": "wo-1",
        "tenant_id": "tenant-1",
        "device_id": "device-1",
        "region": "east",
        "required_skills": ["plc"],
        "version": 3,
        "captured_at": NOW,
    }
    return WorkOrderSnapshot(**(data | updates))


# 构造可按字段覆盖的合格工作人员快照。
def make_worker(worker_id: str, **updates) -> WorkerSnapshot:
    data = {
        "worker_id": worker_id,
        "tenant_id": "tenant-1",
        "region": "east",
        "skills": {"plc": 0.9},
        "current_load": 1,
        "capacity": 5,
        "distance_km": 8,
        "sla_readiness": 0.8,
        "captured_at": NOW,
    }
    return WorkerSnapshot(**(data | updates))


# 构造事件与租户血缘一致的运行时输入。
def make_input(event_id: str = "event-1") -> DispatchRuntimeInput:
    request = DispatchRequest(
        dispatch_id=f"dispatch-{event_id}",
        event_id=event_id,
        tenant_id="tenant-1",
        requested_at=NOW,
    )
    return DispatchRuntimeInput(
        request=request,
        work_order_id="wo-1",
        context=RequestContext(
            trace_id=f"trace-{event_id}",
            tenant_id="tenant-1",
            event_id=event_id,
            permissions=["dispatch:read", "dispatch:write", "dispatch:audit"],
            deadline=datetime.now(UTC) + timedelta(minutes=2),
        ),
    )


# 装配使用临时 Skill 注册表、内存仓库和 Fake Tool 的运行时。
def make_runtime(
    tmp_path: Path,
    order: WorkOrderSnapshot,
    workers: list[WorkerSnapshot],
    *,
    active_skill: DispatchSkill | None = None,
    max_attempts: int = 2,
):
    registry = FileDispatchSkillRegistry(tmp_path / "registry.json")
    loader = DispatchSkillLoader()
    skills = loader.load_directory(BUILTIN)
    for skill in skills:
        registry.register(skill)
    if active_skill:
        registry.register(active_skill)
        registry.activate(active_skill.skill_id, active_skill.skill_version)
    else:
        registry.activate("balanced", "1.0.0")
    adapter = FakeDispatchToolAdapter([order], workers)
    gateway = DispatchToolGateway(adapter, max_attempts=max_attempts)
    decision_service = DispatchDecisionService(
        registry, InMemoryDispatchDecisionRepository()
    )
    return DispatchAgentRuntime(decision_service, gateway), adapter, gateway


# 验证低风险决策能够完成写入、结果核验和审计。
async def test_low_risk_dispatch_executes_verifies_and_audits(tmp_path: Path) -> None:
    runtime, adapter, _ = make_runtime(
        tmp_path,
        make_order(),
        [make_worker("worker-best"), make_worker("worker-busy", current_load=4)],
    )

    result = await runtime.start(make_input())

    assert result.status == RuntimeStatus.AUDITED
    assert result.interrupted is False
    assert result.assignment_outcome is not None
    assert result.assignment_outcome.assigned_worker_id == "worker-best"
    assert adapter.side_effect_counts[ToolName.CREATE_ASSIGNMENT.value] == 1
    assert adapter.side_effect_counts[ToolName.PUBLISH_DISPATCH_AUDIT.value] == 1
    history = await runtime.state_history(result.thread_id)
    assert any(item.get("runtime_status") == RuntimeStatus.VERIFIED for item in history)


# 验证不同派单线程的检查点状态相互隔离。
async def test_checkpoint_threads_keep_dispatch_state_isolated(tmp_path: Path) -> None:
    runtime, adapter, _ = make_runtime(
        tmp_path, make_order(), [make_worker("worker-1")]
    )
    second_order = make_order().model_copy(update={"work_order_id": "wo-2"}, deep=True)
    adapter.work_orders[second_order.work_order_id] = second_order
    first_input = make_input("thread-1")
    second_input = make_input("thread-2").model_copy(
        update={"work_order_id": "wo-2"}, deep=True
    )

    first = await runtime.start(first_input)
    second = await runtime.start(second_input)
    first_history = await runtime.state_history(first.thread_id)
    second_history = await runtime.state_history(second.thread_id)

    assert first.status == second.status == RuntimeStatus.AUDITED
    assert {item["work_order_id"] for item in first_history if "work_order_id" in item} == {
        "wo-1"
    }
    assert {
        item["work_order_id"] for item in second_history if "work_order_id" in item
    } == {"wo-2"}
    assert adapter.side_effect_counts[ToolName.CREATE_ASSIGNMENT.value] == 2


# 验证人工场景会暂停，并在批准恢复后只执行一次派单副作用。
async def test_manual_decision_pauses_and_approved_resume_executes_once(
    tmp_path: Path,
) -> None:
    runtime, adapter, _ = make_runtime(
        tmp_path,
        make_order(priority=WorkOrderPriority.URGENT),
        [make_worker("worker-approved")],
    )

    paused = await runtime.start(make_input("manual-approve"))
    assert paused.interrupted is True
    assert paused.status == RuntimeStatus.AWAITING_APPROVAL
    assert adapter.side_effect_counts[ToolName.CREATE_ASSIGNMENT.value] == 0

    completed = await runtime.resume(
        paused.thread_id,
        ApprovalDecision(
            approved=True,
            reviewer_id="admin-1",
            worker_id="worker-approved",
            reason="urgent work order reviewed",
        ),
    )
    assert completed.status == RuntimeStatus.AUDITED
    assert completed.approval is not None and completed.approval.approved
    assert adapter.side_effect_counts[ToolName.CREATE_ASSIGNMENT.value] == 1


async def test_resume_renews_execution_deadline_after_human_wait(tmp_path: Path) -> None:
    runtime, adapter, _ = make_runtime(
        tmp_path,
        make_order(priority=WorkOrderPriority.URGENT),
        [make_worker("worker-approved")],
    )
    runtime_input = make_input("renew-deadline")
    runtime_input.context.deadline = datetime.now(UTC) + timedelta(seconds=1)
    runtime_input.context.execution_timeout_seconds = 2
    runtime_input.context.approval_expires_at = datetime.now(UTC) + timedelta(minutes=5)

    paused = await runtime.start(runtime_input)
    await asyncio.sleep(1.05)
    completed = await runtime.resume(
        paused.thread_id,
        ApprovalDecision(
            approved=True,
            reviewer_id="admin-1",
            worker_id="worker-approved",
            reason="approval within TTL",
        ),
    )

    assert completed.status == RuntimeStatus.AUDITED
    assert adapter.side_effect_counts[ToolName.CREATE_ASSIGNMENT.value] == 1


async def test_resume_rejects_expired_approval_and_other_tenant(tmp_path: Path) -> None:
    runtime, adapter, _ = make_runtime(
        tmp_path,
        make_order(priority=WorkOrderPriority.URGENT),
        [make_worker("worker-approved")],
    )
    runtime_input = make_input("expired-approval")
    runtime_input.context.approval_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    paused = await runtime.start(runtime_input)
    approval = ApprovalDecision(
        approved=True,
        reviewer_id="admin-1",
        worker_id="worker-approved",
        reason="late approval",
    )

    with pytest.raises(ApprovalValidationError, match="another tenant"):
        await runtime.resume(paused.thread_id, approval, tenant_id="tenant-2")
    with pytest.raises(ApprovalValidationError, match="expired"):
        await runtime.resume(paused.thread_id, approval, tenant_id="tenant-1")
    assert adapter.side_effect_counts[ToolName.CREATE_ASSIGNMENT.value] == 0


def test_runtime_result_does_not_serialize_internal_state() -> None:
    result = RuntimeResult(
        thread_id="dispatch-1",
        status=RuntimeStatus.AWAITING_APPROVAL,
        state={"context": {"permissions": ["dispatch:write"]}, "skill": {"id": "x"}},
    )

    assert "state" not in result.model_dump(mode="json")


# 验证人工拒绝只发布审计而不创建派单。
async def test_manual_rejection_audits_without_assignment(tmp_path: Path) -> None:
    runtime, adapter, _ = make_runtime(
        tmp_path,
        make_order(priority=WorkOrderPriority.URGENT),
        [make_worker("worker-1")],
    )
    paused = await runtime.start(make_input("manual-deny"))

    denied = await runtime.resume(
        paused.thread_id,
        ApprovalDecision(
            approved=False,
            reviewer_id="admin-1",
            reason="insufficient evidence",
        ),
    )

    assert denied.status == RuntimeStatus.DENIED
    assert adapter.side_effect_counts[ToolName.CREATE_ASSIGNMENT.value] == 0
    assert adapter.side_effect_counts[ToolName.PUBLISH_DISPATCH_AUDIT.value] == 1


# 验证人工审批不能选择冻结候选集之外的工作人员。
async def test_approval_cannot_select_worker_outside_frozen_candidates(
    tmp_path: Path,
) -> None:
    runtime, adapter, _ = make_runtime(
        tmp_path,
        make_order(priority=WorkOrderPriority.URGENT),
        [make_worker("worker-eligible")],
    )
    paused = await runtime.start(make_input("invalid-approval"))

    with pytest.raises(ApprovalValidationError, match="not an eligible candidate"):
        await runtime.resume(
            paused.thread_id,
            ApprovalDecision(
                approved=True,
                reviewer_id="admin-1",
                worker_id="worker-injected",
                reason="attempt to bypass candidates",
            ),
        )
    assert adapter.side_effect_counts[ToolName.CREATE_ASSIGNMENT.value] == 0


# 验证暂停任务恢复时继续使用开始阶段冻结的 Skill。
async def test_paused_task_keeps_frozen_skill_after_active_switch(
    tmp_path: Path,
) -> None:
    runtime, adapter, _ = make_runtime(
        tmp_path,
        make_order(priority=WorkOrderPriority.URGENT),
        [make_worker("worker-1")],
    )
    paused = await runtime.start(make_input("frozen-skill"))
    runtime.decision_service.registry.activate("sla-first", "1.0.0")

    completed = await runtime.resume(
        paused.thread_id,
        ApprovalDecision(
            approved=True,
            reviewer_id="admin-1",
            worker_id="worker-1",
            reason="approved under frozen policy",
        ),
    )

    assert completed.state["skill"]["skill_id"] == "balanced"
    assert completed.decision is not None
    assert completed.decision["skill_id"] == "balanced"
    assert adapter.side_effect_counts[ToolName.CREATE_ASSIGNMENT.value] == 1


# 验证核验依赖失败后可从检查点恢复且不会重复写入。
async def test_failed_verify_resumes_from_checkpoint_without_duplicate_write(
    tmp_path: Path,
) -> None:
    runtime, adapter, _ = make_runtime(
        tmp_path, make_order(), [make_worker("worker-1")], max_attempts=2
    )
    adapter.fail_next(ToolName.GET_ASSIGNMENT_OUTCOME, times=2)

    with pytest.raises(DependencyUnavailableError):
        await runtime.start(make_input("recover"))
    assert adapter.side_effect_counts[ToolName.CREATE_ASSIGNMENT.value] == 1

    completed = await runtime.retry("dispatch:tenant-1:dispatch-recover")
    assert completed.status == RuntimeStatus.AUDITED
    assert adapter.side_effect_counts[ToolName.CREATE_ASSIGNMENT.value] == 1


# 验证缺少写工具声明的 Skill 无法执行派单写入。
async def test_skill_without_write_permission_cannot_execute_assignment(
    tmp_path: Path,
) -> None:
    base = DispatchSkillLoader().load(BUILTIN / "balanced-v1.json")
    payload = base.model_dump(mode="json", exclude={"content_hash", "status"})
    payload.update({"skill_id": "read-only", "skill_version": "1.0.0"})
    payload["tool_policy"]["allowed_write_tools"] = ["publish_dispatch_audit"]
    read_only = DispatchSkill.model_validate(payload)
    runtime, adapter, _ = make_runtime(
        tmp_path, make_order(), [make_worker("worker-1")], active_skill=read_only
    )

    with pytest.raises(ToolAccessDeniedError, match="frozen skill"):
        await runtime.start(make_input("read-only"))
    assert adapter.side_effect_counts[ToolName.CREATE_ASSIGNMENT.value] == 0
