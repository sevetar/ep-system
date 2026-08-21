import pytest

from flowfix_agent.memory.conversation import (
    ConversationNamespace,
    ConversationService,
    SQLiteConversationStore,
)
from flowfix_agent.memory.errors import MemoryConflictError
from flowfix_agent.memory.task_artifact import (
    SQLiteTaskArtifactStore,
    TaskArtifactRecord,
)


def test_conversation_is_isolated_rewritten_compressed_and_finalized(tmp_path):
    store = SQLiteConversationStore(tmp_path / "conversation.db")
    service = ConversationService(store, recent_limit=2)
    ns = ConversationNamespace(tenant_id="t1", user_id="u1", thread_id="th1")
    first = service.prepare(ns, "设备 DEV-1 的手册怎么说？")
    service.record_turn(first, "第一轮回答")

    follow_up = service.prepare(ns, "它怎么重启？")
    assert "设备 DEV-1" in follow_up.rewritten_query
    saved = service.record_turn(follow_up, "第二轮回答", end_conversation=True)

    assert saved.version == 2
    assert saved.rolling_summary
    assert saved.final_summary is not None
    assert store.load(
        ConversationNamespace(tenant_id="t2", user_id="u1", thread_id="th1")
    ) is None


def test_task_artifact_store_survives_reopen_and_rejects_stale_version(tmp_path):
    path = tmp_path / "task.db"
    store = SQLiteTaskArtifactStore(path)
    record = TaskArtifactRecord(
        tenant_id="t1",
        thread_id="th1",
        plan_id="p1",
        entity_id="task-1",
        kind="task",
        payload={"status": "pending"},
        source="test",
        trace_id="trace-1",
    )
    saved = store.put(record, expected_version=0)
    reopened = SQLiteTaskArtifactStore(path)

    assert reopened.get("t1", "th1", "p1", "task-1", "task") == saved
    with pytest.raises(MemoryConflictError):
        reopened.put(record, expected_version=0)
