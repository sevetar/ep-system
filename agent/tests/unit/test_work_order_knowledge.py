from datetime import UTC, datetime
from pathlib import Path

from flowfix_agent.adapters.catalog import FileKnowledgeCatalog
from flowfix_agent.knowledge.ledger import FileWorkOrderKnowledgeLedger
from flowfix_agent.knowledge.markdown import MarkdownKnowledgeLoader
from flowfix_agent.knowledge.quality import WorkOrderKnowledgeQualityGate
from flowfix_agent.knowledge.service import KnowledgeIngestionService
from flowfix_agent.knowledge.work_order import WorkOrderCaseIngestionService
from flowfix_agent.messaging.models import WorkOrderCompletedEvent


class FakeEmbedding:
    dimensions = 2

    async def embed_documents(self, texts):
        return [[1.0, 0.0] for _ in texts]


class CapturingIndex:
    index_name = "test-index"

    def __init__(self):
        self.counts = {}
        self.chunks = []

    async def ensure_index(self, recreate=False):
        return None

    async def index_chunks(self, chunks):
        self.chunks.extend(chunks)
        self.counts[chunks[0].knowledge_key] = len(chunks)
        return len(chunks)

    async def count_knowledge_key(self, knowledge_key):
        return self.counts.get(knowledge_key, 0)

    async def delete_source(self, source_id):
        before = len(self.chunks)
        self.chunks = [chunk for chunk in self.chunks if chunk.source_id != source_id]
        return before - len(self.chunks)


class CapturingTrace:
    def __init__(self):
        self.events = []

    async def emit(self, event_type, trace_id, payload):
        self.events.append((event_type, trace_id, payload))


def _event() -> WorkOrderCompletedEvent:
    return WorkOrderCompletedEvent(
        event_id="event-88",
        tenant_id="tenant-a",
        work_order_id="88",
        work_order_version=3,
        device_id="device-7",
        description="空调不制冷",
        repair_process="检查压缩机并补充制冷剂",
        solution="恢复制冷并观察 30 分钟",
        root_cause="制冷剂泄漏导致压力不足",
        verification_result="连续运行三十分钟，温度恢复正常",
        replaced_parts="密封圈",
        device_category="空调",
        device_model="AC-2026",
        knowledge_tags=["不制冷", "制冷剂"],
        completed_at=datetime(2026, 8, 14, 9, 30, tzinfo=UTC),
        trace_id="trace-88",
    )


async def test_work_order_event_becomes_tenant_incident_case(tmp_path: Path):
    root = tmp_path / "knowledge"
    root.mkdir()
    index = CapturingIndex()
    trace = CapturingTrace()
    catalog = FileKnowledgeCatalog(tmp_path / "catalog.json")
    ledger = FileWorkOrderKnowledgeLedger(tmp_path / "ledger.json")
    ingestion = KnowledgeIngestionService(
            MarkdownKnowledgeLoader(root, chunk_size=200, chunk_overlap=20),
            FakeEmbedding(),
            index,
            catalog,
            trace,
            embedding_batch_size=4,
        )
    service = WorkOrderCaseIngestionService(
        ingestion, ledger, WorkOrderKnowledgeQualityGate(), catalog, index, trace
    )

    first = await service.ingest(_event())
    second = await service.ingest(_event())
    active = await catalog.get("work-order/tenant-a/88")

    assert first.status == "indexed"
    assert second.status == "indexed"
    assert active is not None
    assert active.tenant_id == "tenant-a"
    assert active.visibility == "tenant"
    assert active.source_type.value == "incident_case"
    assert index.chunks[0].metadata["work_order_id"] == "88"
    assert index.chunks[0].metadata["device_id"] == "device-7"
    assert index.chunks[0].metadata["device_model"] == "AC-2026"
    full_content = "\n".join(chunk.content for chunk in index.chunks)
    assert "故障现象" in full_content
    assert "处理过程" in full_content
    assert "解决方案" in full_content
    assert "根因分析" in full_content
    assert "修复验证" in full_content
    assert any(item[1] == "trace-88" for item in trace.events)

    status = await service.get_status("event-88")
    assert status is not None
    assert status.status.value == "indexed"
    assert status.attempts == 1

    deleted = await service.revoke("tenant-a", "88", "工单重新打开")
    assert deleted > 0
    assert await catalog.get("work-order/tenant-a/88") is None
    assert (await service.get_status("event-88")).status.value == "revoked"


async def test_quality_gate_rejects_short_case_without_embedding(tmp_path: Path):
    root = tmp_path / "knowledge"
    root.mkdir()
    index = CapturingIndex()
    trace = CapturingTrace()
    catalog = FileKnowledgeCatalog(tmp_path / "catalog.json")
    ledger = FileWorkOrderKnowledgeLedger(tmp_path / "ledger.json")
    ingestion = KnowledgeIngestionService(
        MarkdownKnowledgeLoader(root, chunk_size=200, chunk_overlap=20),
        FakeEmbedding(), index, catalog, trace, embedding_batch_size=4,
    )
    service = WorkOrderCaseIngestionService(
        ingestion, ledger, WorkOrderKnowledgeQualityGate(), catalog, index, trace
    )
    bad = _event().model_copy(
        update={"event_id": "event-bad", "repair_process": "处理", "solution": "修复"}
    )

    result = await service.ingest(bad)

    assert result.status.value == "rejected"
    assert "repair_process_too_short" in result.quality_issues
    assert index.chunks == []


async def test_sensitive_values_are_redacted_before_indexing(tmp_path: Path):
    root = tmp_path / "knowledge"
    root.mkdir()
    index = CapturingIndex()
    trace = CapturingTrace()
    catalog = FileKnowledgeCatalog(tmp_path / "catalog.json")
    ledger = FileWorkOrderKnowledgeLedger(tmp_path / "ledger.json")
    ingestion = KnowledgeIngestionService(
        MarkdownKnowledgeLoader(root, chunk_size=200, chunk_overlap=20),
        FakeEmbedding(), index, catalog, trace, embedding_batch_size=4,
    )
    service = WorkOrderCaseIngestionService(
        ingestion, ledger, WorkOrderKnowledgeQualityGate(), catalog, index, trace
    )
    event = _event().model_copy(
        update={"event_id": "event-pii", "description": "空调不制冷，联系 13812345678 处理"}
    )

    await service.ingest(event)

    content = "\n".join(chunk.content for chunk in index.chunks)
    assert "13812345678" not in content
    assert "[已脱敏手机号]" in content
    assert "description" in (await service.get_status("event-pii")).redacted_fields
