import os
from datetime import UTC, datetime
from urllib.parse import urlsplit

import pytest

from flowfix_agent.dispatch.adapters.mysql_decision_repository import (
    MySQLDispatchDecisionRepository,
)
from flowfix_agent.dispatch.domain.models import (
    DispatchDecision,
    DispatchOutcome,
    DispatchStatus,
    RiskLevel,
)
from flowfix_agent.memory.mysql import MySQLStoreConfig


# 从 MYSQL_TEST_URL 解析连接配置，未设置时跳过。
def mysql_config() -> MySQLStoreConfig:
    url = os.getenv("MYSQL_TEST_URL")
    if not url:
        pytest.skip("set MYSQL_TEST_URL to run the MySQL component test")
    parts = urlsplit(url)
    return MySQLStoreConfig(
        host=parts.hostname or "127.0.0.1",
        port=parts.port or 3306,
        user=parts.username or "root",
        password=parts.password,
        database=parts.path.lstrip("/") or "flowfix_agent",
    )


# 构造一份满足模型约束的最小派单决策。
def _decision(event_id: str) -> DispatchDecision:
    return DispatchDecision(
        decision_id=f"decision-{event_id}",
        dispatch_id=f"dispatch-{event_id}",
        event_id=event_id,
        tenant_id="tenant-1",
        work_order_id="wo-1",
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


# 验证真实 MySQL 决策仓库的幂等保存与事件级读取语义。
@pytest.mark.integration
async def test_mysql_decision_repository_roundtrip_and_idempotent():
    repository = MySQLDispatchDecisionRepository(mysql_config())
    event_id = f"event-{datetime.now(UTC).timestamp():.0f}"

    assert await repository.get_by_event(event_id) is None
    await repository.save_if_absent(_decision(event_id))
    await repository.save_if_absent(_decision(event_id))
    loaded = await repository.get_by_event(event_id)

    assert loaded is not None
    assert loaded.event_id == event_id
    assert loaded.selected_worker_id == "worker-1"
