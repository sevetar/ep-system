from datetime import UTC, datetime
from pathlib import Path

import pytest

from flowfix_agent.dispatch.adapters.decision_repository import InMemoryDispatchDecisionRepository
from flowfix_agent.dispatch.adapters.skill_registry import FileDispatchSkillRegistry
from flowfix_agent.dispatch.application.errors import IdempotencyConflictError
from flowfix_agent.dispatch.application.service import DispatchDecisionService
from flowfix_agent.dispatch.domain.models import (
    DispatchOutcome,
    DispatchRequest,
    DispatchStatus,
    WorkerSnapshot,
    WorkOrderSnapshot,
    WorkOrderStatus,
)
from flowfix_agent.dispatch.skills.loader import DispatchSkillLoader

BUILTIN = Path("src/flowfix_agent/dispatch/skills/builtin")
NOW = datetime(2026, 8, 4, 8, 0, tzinfo=UTC)


# 记录派单服务发出的事件，供场景测试断言审计内容。
class FakeTrace:
    # 初始化空的追踪事件列表。
    def __init__(self) -> None:
        self.events: list[dict] = []

    # 保存事件类型、追踪标识和结构化载荷。
    async def emit(self, event_type, trace_id, payload) -> None:
        self.events.append(
            {"event_type": event_type, "trace_id": trace_id, "payload": payload}
        )


# 构造使用固定租户和时间的派单请求。
def make_request(event_id: str = "event-1") -> DispatchRequest:
    return DispatchRequest(
        dispatch_id=f"dispatch-{event_id}",
        event_id=event_id,
        tenant_id="tenant-1",
        requested_at=NOW,
    )


# 构造可覆盖字段的待派单工单快照。
def make_order(**updates) -> WorkOrderSnapshot:
    data = {
        "work_order_id": "wo-1",
        "tenant_id": "tenant-1",
        "device_id": "device-1",
        "region": "east",
        "required_skills": ["plc"],
        "version": 7,
        "captured_at": NOW,
    }
    return WorkOrderSnapshot(**(data | updates))


# 构造可覆盖字段的工作人员快照。
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


# 装配指定激活 Skill、内存决策仓库和 Fake Trace 的服务。
def make_service(tmp_path: Path, active: str = "balanced"):
    registry = FileDispatchSkillRegistry(tmp_path / "registry.json")
    for skill in DispatchSkillLoader().load_directory(BUILTIN):
        registry.register(skill)
    registry.activate(active, "1.0.0")
    trace = FakeTrace()
    service = DispatchDecisionService(
        registry, InMemoryDispatchDecisionRepository(), trace
    )
    return service, registry, trace


# 验证基准策略产生可解释、可追踪的自动分配结果。
async def test_baseline_produces_auditable_assignment(tmp_path: Path) -> None:
    service, _, trace = make_service(tmp_path)
    decision = await service.decide(
        make_request(),
        make_order(),
        [
            make_worker("worker-good"),
            make_worker("worker-busy", current_load=4, distance_km=30),
        ],
    )

    assert decision.outcome == DispatchOutcome.ASSIGN
    assert decision.status == DispatchStatus.DECIDED
    assert decision.selected_worker_id == "worker-good"
    assert decision.skill_id == "balanced"
    assert decision.external_execution_status == "not_started"
    assert decision.input_fingerprint and decision.decision_fingerprint
    assert len(decision.transitions) == 2
    assert trace.events[0]["event_type"] == "dispatch.decision"


# 验证非法工单在候选筛选前被拒绝。
async def test_invalid_order_is_rejected_before_candidate_selection(
    tmp_path: Path,
) -> None:
    service, _, _ = make_service(tmp_path)
    decision = await service.decide(
        make_request(),
        make_order(status=WorkOrderStatus.ASSIGNED, assigned_worker_id="worker-old"),
        [make_worker("worker-good")],
    )
    assert decision.outcome == DispatchOutcome.REJECTED
    assert decision.selected_worker_id is None
    assert "work_order_already_assigned" in decision.reasons


# 验证没有合格候选时决策进入人工处理分支。
async def test_no_eligible_candidate_enters_manual_queue(tmp_path: Path) -> None:
    service, _, _ = make_service(tmp_path)
    decision = await service.decide(
        make_request(), make_order(), [make_worker("worker-off", available=False)]
    )
    assert decision.outcome == DispatchOutcome.MANUAL
    assert decision.risk_level == "high"
    assert decision.exclusions[0].reasons == ["worker_unavailable"]


# 验证相同事件可幂等重放，而输入变化会触发冲突。
async def test_same_event_is_idempotent_but_different_input_conflicts(
    tmp_path: Path,
) -> None:
    service, _, _ = make_service(tmp_path)
    first = await service.decide(
        make_request(), make_order(), [make_worker("worker-good")]
    )
    replay = await service.decide(
        make_request(), make_order(), [make_worker("worker-good")]
    )
    assert replay == first

    with pytest.raises(IdempotencyConflictError):
        await service.decide(
            make_request(),
            make_order(version=8),
            [make_worker("worker-good")],
        )


# 验证激活策略切换只影响切换后准备的新任务。
async def test_active_switch_only_affects_new_tasks(tmp_path: Path) -> None:
    service, registry, _ = make_service(tmp_path)
    old_task = service.prepare(
        make_request("old"), make_order(), [make_worker("worker-good")]
    )
    registry.activate("sla-first", "1.0.0")

    old_decision = await service.decide_prepared(old_task)
    new_decision = await service.decide(
        make_request("new"), make_order(), [make_worker("worker-good")]
    )
    assert old_decision.skill_id == "balanced"
    assert new_decision.skill_id == "sla-first"


# 验证策略切换和回滚会恢复对应的预期候选选择。
async def test_strategy_change_and_rollback_change_expected_selection(
    tmp_path: Path,
) -> None:
    service, registry, _ = make_service(tmp_path)
    workers = [
        make_worker(
            "worker-near", distance_km=2, current_load=0, sla_readiness=0.2
        ),
        make_worker(
            "worker-sla", region="west", distance_km=40, current_load=2, sla_readiness=1.0
        ),
    ]
    balanced = await service.decide(make_request("balanced"), make_order(), workers)
    registry.activate("sla-first", "1.0.0")
    sla_first = await service.decide(make_request("sla"), make_order(), workers)
    registry.rollback()
    restored = await service.decide(make_request("restored"), make_order(), workers)

    assert balanced.selected_worker_id == "worker-near"
    assert sla_first.selected_worker_id == "worker-sla"
    assert restored.selected_worker_id == "worker-near"
    assert restored.skill_id == "balanced"
