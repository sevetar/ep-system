from datetime import UTC, datetime
from pathlib import Path

import pytest

from flowfix_agent.dispatch.adapters.fake_tools import FakeDispatchToolAdapter
from flowfix_agent.dispatch.adapters.proposal_bridge import ProposalDispatchBridge
from flowfix_agent.dispatch.adapters.skill_registry import FileDispatchSkillRegistry
from flowfix_agent.dispatch.adapters.sqlite_decision_repository import (
    SQLiteDispatchDecisionRepository,
)
from flowfix_agent.dispatch.application.errors import IdempotencyConflictError
from flowfix_agent.dispatch.application.service import DispatchDecisionService
from flowfix_agent.dispatch.domain.models import (
    DispatchOutcome,
    WorkerSnapshot,
    WorkOrderPriority,
    WorkOrderSnapshot,
)
from flowfix_agent.dispatch.runtime.graph import DispatchAgentRuntime
from flowfix_agent.dispatch.runtime.middleware import DispatchToolGateway
from flowfix_agent.dispatch.runtime.models import RuntimeStatus, ToolName
from flowfix_agent.dispatch.skills.loader import DispatchSkillLoader
from flowfix_agent.planning.models import DispatchProposal

BUILTIN = Path("src/flowfix_agent/dispatch/skills/builtin")
NOW = datetime(2026, 8, 6, 14, 0, tzinfo=UTC)


# 构造一份通过完成门禁的合规只读派单建议。
def _proposal() -> DispatchProposal:
    return DispatchProposal(
        proposal_id="proposal-inc1-v1",
        incident_id="inc1",
        plan_id="plan-inc1",
        plan_version=1,
        work_order_id="wo-1",
        proposed_action="依据调查结果更换电源模块并安排处置窗口",
        reason="完成门禁通过，基于调查制品生成建议。",
        risk_level="medium",
        evidence_refs=["chunk-1"],
        requires_approval=True,
    )


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


# 验证 SQLite 持久化决策仓库下转交流程仍强制人工审批并落库。
async def test_transfer_persists_decision_to_durable_repository(
    tmp_path: Path,
) -> None:
    registry = _registry(tmp_path)
    repository = SQLiteDispatchDecisionRepository(tmp_path / "decisions.db")
    adapter = FakeDispatchToolAdapter([_order()], [_worker()])
    bridge = ProposalDispatchBridge(
        DispatchAgentRuntime(
            DispatchDecisionService(registry, repository),
            DispatchToolGateway(adapter, max_attempts=2),
        )
    )

    result = await bridge.transfer(_proposal(), tenant_id="tenant-1")

    assert result.interrupted is True
    assert result.status == RuntimeStatus.AWAITING_APPROVAL
    event_id = result.decision["event_id"]
    saved = await repository.get_by_event(event_id)
    assert saved is not None
    assert saved.outcome == DispatchOutcome.ASSIGN


# 验证重启（重建仓库与运行时）后同一事件决策仍从磁盘恢复，重复转交复用原决策。
async def test_decision_survives_restart_and_is_reused(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    path = tmp_path / "decisions.db"
    repository = SQLiteDispatchDecisionRepository(path)
    adapter = FakeDispatchToolAdapter([_order()], [_worker()])
    bridge = ProposalDispatchBridge(
        DispatchAgentRuntime(
            DispatchDecisionService(registry, repository),
            DispatchToolGateway(adapter, max_attempts=2),
        )
    )

    result = await bridge.transfer(_proposal(), tenant_id="tenant-1")
    event_id = result.decision["event_id"]

    # 重启：以同一路径重建仓库与运行时，决策应从磁盘恢复。
    restarted_repository = SQLiteDispatchDecisionRepository(path)
    assert await restarted_repository.get_by_event(event_id) is not None

    # 同一事件再次转交（新提案时间戳不同 → 输入指纹冲突）必须被持久化仓库拒绝，
    # 证明重启后幂等防线仍生效，绝不产生第二个决策或真实写入。
    restarted_adapter = FakeDispatchToolAdapter([_order()], [_worker()])
    restarted_bridge = ProposalDispatchBridge(
        DispatchAgentRuntime(
            DispatchDecisionService(registry, restarted_repository),
            DispatchToolGateway(restarted_adapter, max_attempts=2),
        )
    )
    with pytest.raises(IdempotencyConflictError):
        await restarted_bridge.transfer(_proposal(), tenant_id="tenant-1")
    assert (
        restarted_adapter.side_effect_counts[ToolName.CREATE_ASSIGNMENT.value] == 0
    )
