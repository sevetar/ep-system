from datetime import UTC, datetime
from pathlib import Path

import pytest

from flowfix_agent.dispatch.application.rules import filter_workers, validate_work_order
from flowfix_agent.dispatch.application.scoring import score_candidates
from flowfix_agent.dispatch.domain.models import (
    DispatchRequest,
    WorkerSnapshot,
    WorkOrderSnapshot,
    WorkOrderStatus,
)
from flowfix_agent.dispatch.skills.loader import DispatchSkillLoader

BUILTIN = Path("src/flowfix_agent/dispatch/skills/builtin")


# 构造可覆盖字段的待派单工单快照。
def order(**updates) -> WorkOrderSnapshot:
    data = {
        "work_order_id": "wo-1",
        "tenant_id": "tenant-1",
        "device_id": "device-1",
        "region": "east",
        "required_skills": ["plc"],
        "version": 3,
        "captured_at": datetime(2026, 8, 4, tzinfo=UTC),
    }
    return WorkOrderSnapshot(**(data | updates))


# 构造可覆盖字段的默认合格工作人员快照。
def worker(worker_id: str, **updates) -> WorkerSnapshot:
    data = {
        "worker_id": worker_id,
        "tenant_id": "tenant-1",
        "region": "east",
        "skills": {"plc": 0.8},
        "current_load": 1,
        "capacity": 4,
        "distance_km": 10,
        "sla_readiness": 0.8,
        "captured_at": datetime(2026, 8, 4, tzinfo=UTC),
    }
    return WorkerSnapshot(**(data | updates))


# 验证跨租户、非待派单和已分配工单始终被硬门禁拒绝。
def test_order_safety_gates_cannot_be_disabled() -> None:
    request = DispatchRequest(
        dispatch_id="d-1", event_id="e-1", tenant_id="tenant-1"
    )
    errors = validate_work_order(
        request,
        order(status=WorkOrderStatus.ASSIGNED, assigned_worker_id="worker-old"),
    )
    assert "work_order_status_not_dispatchable:assigned" in errors
    assert "work_order_already_assigned" in errors


# 验证每类不合格工作人员都会产生明确的排除原因。
@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"available": False}, "worker_unavailable"),
        ({"shift_active": False}, "shift_inactive"),
        ({"current_load": 4}, "capacity_exhausted"),
        ({"skills": {"hvac": 1.0}}, "missing_skills:plc"),
        ({"region": "west"}, "region_mismatch"),
        ({"distance_km": 80}, "distance_exceeded"),
    ],
)
def test_worker_exclusion_is_explainable(changes, reason) -> None:
    skill = DispatchSkillLoader().load(BUILTIN / "balanced-v1.json")
    result = filter_workers(order(), [worker("worker-1", **changes)], skill)
    assert result.eligible == []
    assert reason in result.exclusions[0].reasons


# 验证候选评分和同分排序在相同输入下保持确定性。
def test_scoring_and_tie_break_are_deterministic() -> None:
    skill = DispatchSkillLoader().load(BUILTIN / "balanced-v1.json")
    scores = score_candidates(
        order(),
        [worker("worker-b"), worker("worker-a")],
        skill,
    )
    assert [score.worker_id for score in scores] == ["worker-a", "worker-b"]
    assert [score.rank for score in scores] == [1, 2]
