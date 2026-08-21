from datetime import UTC, datetime
from pathlib import Path

from flowfix_agent.dispatch.adapters.sqlite_decision_repository import (
    SQLiteDispatchDecisionRepository,
)
from flowfix_agent.dispatch.domain.models import (
    DispatchDecision,
    DispatchOutcome,
    DispatchStatus,
    RiskLevel,
)


# 构造一份满足模型约束的最小派单决策。
def _decision(event_id: str, work_order_id: str) -> DispatchDecision:
    return DispatchDecision(
        decision_id=f"decision-{event_id}",
        dispatch_id=f"dispatch-{event_id}",
        event_id=event_id,
        tenant_id="tenant-1",
        work_order_id=work_order_id,
        work_order_version=1,
        status=DispatchStatus.DECIDED,
        outcome=DispatchOutcome.ASSIGN,
        selected_worker_id="worker-1",
        risk_level=RiskLevel.LOW,
        skill_id="balanced",
        skill_version="1.0.0",
        skill_content_hash="hash-1",
        input_fingerprint="input-1",
        decision_fingerprint="decision-1",
        reasons=["worker_suitability_ok"],
        decided_at=datetime(2026, 8, 6, 8, 0, tzinfo=UTC),
    )


# 验证 SQLite 仓库首次写入返回副本，重复保存返回已存在的原始决策。
async def test_save_if_absent_is_idempotent(tmp_path: Path) -> None:
    repository = SQLiteDispatchDecisionRepository(tmp_path / "decisions.db")
    decision = _decision("event-1", "wo-1")

    first = await repository.save_if_absent(decision)
    second = await repository.save_if_absent(decision)

    assert first.event_id == "event-1"
    assert second.event_id == "event-1"
    assert first.selected_worker_id == "worker-1"


# 验证读取未保存事件返回 None，读取已保存事件返回隔离的深拷贝。
async def test_get_by_event_roundtrip(tmp_path: Path) -> None:
    repository = SQLiteDispatchDecisionRepository(tmp_path / "decisions.db")
    decision = _decision("event-2", "wo-2")

    assert await repository.get_by_event("event-2") is None
    await repository.save_if_absent(decision)
    loaded = await repository.get_by_event("event-2")

    assert loaded is not None
    assert loaded.work_order_id == "wo-2"
    loaded.selected_worker_id = "mutated"
    again = await repository.get_by_event("event-2")
    assert again.selected_worker_id == "worker-1"


# 验证重启后决策仍可读取：用同一路径重建仓库模拟进程重启。
async def test_decision_survives_restart(tmp_path: Path) -> None:
    path = tmp_path / "decisions.db"
    first = SQLiteDispatchDecisionRepository(path)
    await first.save_if_absent(_decision("event-3", "wo-3"))

    # 重新实例化仓库读取同一文件，验证持久化而非内存态。
    restarted = SQLiteDispatchDecisionRepository(path)
    loaded = await restarted.get_by_event("event-3")

    assert loaded is not None
    assert loaded.event_id == "event-3"
    assert loaded.work_order_id == "wo-3"
