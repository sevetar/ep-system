import os
import uuid
from urllib.parse import urlsplit

import pytest

from flowfix_agent.memory.conversation import (
    ConversationNamespace,
    ConversationService,
    MySQLConversationStore,
)
from flowfix_agent.memory.errors import MemoryConflictError
from flowfix_agent.memory.mysql import MySQLStoreConfig
from flowfix_agent.memory.task_artifact import MySQLTaskArtifactStore, TaskArtifactRecord


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


# 验证真实 MySQL 会话存储的隔离、改写、压缩、总结与版本冲突语义。
@pytest.mark.integration
async def test_mysql_conversation_roundtrip_and_version_conflict():
    store = MySQLConversationStore(mysql_config())
    service = ConversationService(store, recent_limit=2)
    ns = ConversationNamespace(
        tenant_id="t-test", user_id="u-test", thread_id=uuid.uuid4().hex[:12]
    )
    first = service.prepare(ns, "设备 DEV-1 的手册怎么说？")
    service.record_turn(first, "第一轮回答")

    follow_up = service.prepare(ns, "它怎么重启？")
    assert "DEV-1" in follow_up.rewritten_query
    saved = service.record_turn(follow_up, "第二轮回答", end_conversation=True)
    assert saved.version == 2
    assert saved.rolling_summary
    assert saved.final_summary is not None

    assert store.load(ns) is not None
    assert store.load(
        ConversationNamespace(tenant_id="t-other", user_id="u-test", thread_id=ns.thread_id)
    ) is None
    with pytest.raises(MemoryConflictError):
        store.save(saved, expected_version=0)


# 验证真实 MySQL Task/Artifact 存储的版本化写入、冲突检测与计划内列表。
@pytest.mark.integration
async def test_mysql_task_artifact_put_get_list_and_conflict():
    config = mysql_config()
    store = MySQLTaskArtifactStore(config)
    reopened = MySQLTaskArtifactStore(config)
    keys = uuid.uuid4().hex[:12]
    record = TaskArtifactRecord(
        tenant_id=f"t-{keys}",
        thread_id="th1",
        plan_id="p1",
        entity_id="task-1",
        kind="task",
        payload={"status": "pending"},
        source="test",
        trace_id="trace-1",
    )
    saved = store.put(record, expected_version=0)

    assert reopened.get(record.tenant_id, "th1", "p1", "task-1", "task") == saved
    assert [
        item.entity_id
        for item in reopened.list_plan(record.tenant_id, "th1", "p1")
    ] == ["task-1"]
    with pytest.raises(MemoryConflictError):
        reopened.put(record, expected_version=0)
    bumped = store.put(record, expected_version=saved.version)
    assert bumped.version == 2
