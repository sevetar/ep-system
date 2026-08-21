from datetime import UTC, datetime
from pathlib import Path

import pytest

from flowfix_agent.dispatch.adapters.decision_repository import InMemoryDispatchDecisionRepository
from flowfix_agent.dispatch.adapters.fake_tools import FakeDispatchToolAdapter
from flowfix_agent.dispatch.adapters.proposal_bridge import ProposalDispatchBridge
from flowfix_agent.dispatch.adapters.skill_registry import FileDispatchSkillRegistry
from flowfix_agent.dispatch.application.errors import IdempotencyConflictError
from flowfix_agent.dispatch.application.service import DispatchDecisionService
from flowfix_agent.dispatch.domain.models import (
    DispatchOutcome,
    WorkerSnapshot,
    WorkOrderPriority,
    WorkOrderSnapshot,
    WorkOrderStatus,
)
from flowfix_agent.dispatch.runtime.graph import DispatchAgentRuntime
from flowfix_agent.dispatch.runtime.middleware import DispatchToolGateway
from flowfix_agent.dispatch.runtime.models import (
    AssignmentOutcomeStatus,
    RuntimeStatus,
    ToolName,
)
from flowfix_agent.dispatch.skills.loader import DispatchSkillLoader
from flowfix_agent.planning.models import DispatchProposal

BUILTIN = Path("src/flowfix_agent/dispatch/skills/builtin")
NOW = datetime(2026, 8, 6, 14, 0, tzinfo=UTC)


# 构造一份通过完成门禁的合规只读派单建议。
def _proposal(**overrides) -> DispatchProposal:
    values = {
        "proposal_id": "proposal-inc1-v1",
        "incident_id": "inc1",
        "plan_id": "plan-inc1",
        "plan_version": 1,
        "work_order_id": "wo-1",
        "proposed_action": "依据调查结果更换电源模块并安排处置窗口",
        "reason": "完成门禁通过，基于调查制品生成建议。",
        "risk_level": "medium",
        "evidence_refs": ["chunk-1"],
        "requires_approval": True,
    }
    values.update(overrides)
    return DispatchProposal(**values)


# 构造一个合格工作人员快照，保证单候选自动决策为 assign。
def _worker() -> WorkerSnapshot:
    return WorkerSnapshot(
        worker_id="worker-best",
        tenant_id="tenant-1",
        region="east",
        skills={"plc": 1.0},
        current_load=0,
        capacity=5,
        distance_km=5,
        sla_readiness=1.0,
        captured_at=NOW,
    )


# 构造一个普通优先级工单，配合合格员工得到可自动派单的 assign 决策。
def _order() -> WorkOrderSnapshot:
    return WorkOrderSnapshot(
        work_order_id="wo-1",
        tenant_id="tenant-1",
        device_id="device-1",
        region="east",
        required_skills=["plc"],
        priority=WorkOrderPriority.NORMAL,
        version=1,
        captured_at=NOW,
    )


# 装配共享仓库与 Fake 适配器的 Skill 注册表（用于幂等重放测试）。
def _registry(tmp_path: Path) -> FileDispatchSkillRegistry:
    registry = FileDispatchSkillRegistry(tmp_path / "registry.json")
    loader = DispatchSkillLoader()
    for skill in loader.load_directory(BUILTIN):
        registry.register(skill)
    registry.activate("balanced", "1.0.0")
    return registry


# 验证调查链建议转交后强制进入人工审批：即使决策可自动派单也必须 HITL。
async def test_transfer_forces_human_approval_on_auto_assign(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    adapter = FakeDispatchToolAdapter([_order()], [_worker()])
    bridge = ProposalDispatchBridge(
        DispatchAgentRuntime(
            DispatchDecisionService(registry, InMemoryDispatchDecisionRepository()),
            DispatchToolGateway(adapter, max_attempts=2),
        )
    )

    result = await bridge.transfer(_proposal(), tenant_id="tenant-1")

    assert result.interrupted is True
    assert result.status == RuntimeStatus.AWAITING_APPROVAL
    # 决策本身是可自动派单的 assign，强制审批开关使其仍停在 HITL。
    assert result.decision["outcome"] == DispatchOutcome.ASSIGN.value
    assert adapter.side_effect_counts[ToolName.CREATE_ASSIGNMENT.value] == 0


# 验证人工批准后完成派单：写入、核验与审计闭环，且工单版本递增。
async def test_approve_completes_dispatch_and_verifies(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    order = _order()
    adapter = FakeDispatchToolAdapter([order], [_worker()])
    bridge = ProposalDispatchBridge(
        DispatchAgentRuntime(
            DispatchDecisionService(registry, InMemoryDispatchDecisionRepository()),
            DispatchToolGateway(adapter, max_attempts=2),
        )
    )

    first = await bridge.transfer(_proposal(), tenant_id="tenant-1")
    result = await bridge.approve(
        first.thread_id,
        reviewer_id="reviewer-1",
        worker_id="worker-best",
        reason="确认处置建议，批准派单",
    )

    assert result.status == RuntimeStatus.AUDITED
    assert not result.interrupted
    assert result.assignment_outcome is not None
    assert result.assignment_outcome.status == AssignmentOutcomeStatus.ASSIGNED
    assert result.assignment_outcome.assigned_worker_id == "worker-best"
    assert adapter.side_effect_counts[ToolName.CREATE_ASSIGNMENT.value] == 1
    assert adapter.work_orders["wo-1"].status == WorkOrderStatus.ASSIGNED
    assert adapter.work_orders["wo-1"].version == 2


# 验证人工拒绝后不产生任何派单写入，直接审计结束。
async def test_deny_skips_assignment_write(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    adapter = FakeDispatchToolAdapter([_order()], [_worker()])
    bridge = ProposalDispatchBridge(
        DispatchAgentRuntime(
            DispatchDecisionService(registry, InMemoryDispatchDecisionRepository()),
            DispatchToolGateway(adapter, max_attempts=2),
        )
    )

    first = await bridge.transfer(_proposal(), tenant_id="tenant-1")
    result = await bridge.deny(
        first.thread_id, reviewer_id="reviewer-1", reason="现场条件不具备，暂缓派单"
    )

    assert result.status == RuntimeStatus.DENIED
    assert not result.interrupted
    assert result.approval is not None and result.approval.approved is False
    assert adapter.side_effect_counts[ToolName.CREATE_ASSIGNMENT.value] == 0
    assert adapter.work_orders["wo-1"].status == WorkOrderStatus.PENDING_DISPATCH


# 验证同一建议在写入前重复转交是幂等的：稳定输入指纹重放同一决策。
async def test_retransfer_before_write_replays_same_decision(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    # 决策仓库在派单运行时之间共享（与生产容器一致），检查点彼此独立。
    repository = InMemoryDispatchDecisionRepository()
    adapter = FakeDispatchToolAdapter([_order()], [_worker()])

    def build_bridge():
        return ProposalDispatchBridge(
            DispatchAgentRuntime(
                DispatchDecisionService(registry, repository),
                DispatchToolGateway(adapter, max_attempts=2),
            )
        )

    # 同一提案对象被重复转交：created_at 稳定，输入指纹一致，决策可重放。
    proposal = _proposal()
    first_bridge = build_bridge()
    first = await first_bridge.transfer(proposal, tenant_id="tenant-1")
    second_bridge = build_bridge()
    second = await second_bridge.transfer(proposal, tenant_id="tenant-1")

    # 两次转交都停在强制人工审批，且决策完全一致。
    assert first.status == RuntimeStatus.AWAITING_APPROVAL
    assert second.status == RuntimeStatus.AWAITING_APPROVAL
    assert second.decision["decision_id"] == first.decision["decision_id"]
    assert second.decision["input_fingerprint"] == first.decision["input_fingerprint"]
    # 尚未写入，工单未被修改。
    assert adapter.work_orders["wo-1"].version == 1

    # 对重放的第二次转交批准后只产生一次真实写入。
    result = await second_bridge.approve(
        second.thread_id,
        reviewer_id="reviewer-1",
        worker_id="worker-best",
        reason="批准重放转交",
    )
    assert result.status == RuntimeStatus.AUDITED
    assert adapter.side_effect_counts[ToolName.CREATE_ASSIGNMENT.value] == 1


# 验证写入成功后的重复转交被拒绝：工单版本已变，绝不静默二次派单。
async def test_retransfer_after_success_is_conflict(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    repository = InMemoryDispatchDecisionRepository()
    adapter = FakeDispatchToolAdapter([_order()], [_worker()])

    def build_bridge():
        return ProposalDispatchBridge(
            DispatchAgentRuntime(
                DispatchDecisionService(registry, repository),
                DispatchToolGateway(adapter, max_attempts=2),
            )
        )

    proposal = _proposal()
    bridge = build_bridge()
    first = await bridge.transfer(proposal, tenant_id="tenant-1")
    await bridge.approve(
        first.thread_id,
        reviewer_id="reviewer-1",
        worker_id="worker-best",
        reason="首次批准",
    )

    # 工单已指派（版本 1→2），同一提案再次转交触发输入指纹冲突。
    assert adapter.work_orders["wo-1"].version == 2
    with pytest.raises(IdempotencyConflictError):
        await build_bridge().transfer(proposal, tenant_id="tenant-1")
