from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from flowfix_agent.knowledge.models import (
    SourceSnapshot,
    SourceType,
    WorkOrderKnowledgeIngestionResult,
    WorkOrderKnowledgeRecord,
    WorkOrderKnowledgeStatus,
)
from flowfix_agent.knowledge.ports import (
    KnowledgeCatalogPort,
    KnowledgeIndexPort,
    TracePort,
    WorkOrderKnowledgeLedgerPort,
)
from flowfix_agent.knowledge.quality import WorkOrderKnowledgeQualityGate
from flowfix_agent.knowledge.service import KnowledgeIngestionService
from flowfix_agent.messaging.models import WorkOrderCompletedEvent

FINAL_STATUSES = {
    WorkOrderKnowledgeStatus.INDEXED,
    WorkOrderKnowledgeStatus.SKIPPED,
    WorkOrderKnowledgeStatus.REJECTED,
    WorkOrderKnowledgeStatus.REVOKED,
}


class WorkOrderCaseIngestionService:
    """把可信工单完成事件投影为租户隔离、可审核和可撤回的维修案例。"""

    def __init__(
        self,
        ingestion: KnowledgeIngestionService,
        ledger: WorkOrderKnowledgeLedgerPort,
        quality_gate: WorkOrderKnowledgeQualityGate,
        catalog: KnowledgeCatalogPort,
        index: KnowledgeIndexPort,
        trace: TracePort,
    ) -> None:
        self.ingestion = ingestion
        self.ledger = ledger
        self.quality_gate = quality_gate
        self.catalog = catalog
        self.index = index
        self.trace = trace

    async def ingest(
        self, event: WorkOrderCompletedEvent
    ) -> WorkOrderKnowledgeIngestionResult:
        sanitized, redacted_fields = self.quality_gate.sanitize(event)
        content = self._content(sanitized)
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        source_id = self.source_id(event.tenant_id, event.work_order_id)
        source_version = f"v{event.work_order_version}-{content_hash[:12]}"

        existing = await self.ledger.get(event.event_id)
        if existing and existing.content_hash != content_hash:
            return WorkOrderKnowledgeIngestionResult(
                event_id=event.event_id,
                tenant_id=event.tenant_id,
                work_order_id=event.work_order_id,
                source_id=source_id,
                version=source_version,
                status=WorkOrderKnowledgeStatus.REJECTED,
                quality_issues=["event_id_payload_conflict"],
                error="same event_id was received with different knowledge content",
            )
        if existing and existing.status in FINAL_STATUSES:
            return self._result(existing)

        assessment = self.quality_gate.assess(sanitized, redacted_fields)
        now = datetime.now(UTC)
        record = WorkOrderKnowledgeRecord(
            event_id=event.event_id,
            tenant_id=event.tenant_id,
            work_order_id=event.work_order_id,
            work_order_version=event.work_order_version,
            source_id=source_id,
            source_version=source_version,
            content_hash=content_hash,
            status=WorkOrderKnowledgeStatus.PROCESSING,
            quality_score=assessment.score,
            quality_issues=assessment.issues,
            redacted_fields=assessment.redacted_fields,
            attempts=(existing.attempts + 1) if existing else 1,
            created_at=existing.created_at if existing else now,
            updated_at=now,
        )
        if not assessment.accepted:
            record.status = WorkOrderKnowledgeStatus.REJECTED
            record.error = "knowledge quality gate rejected the work order"
            await self.ledger.save(record)
            await self.trace.emit(
                "knowledge.work_order_rejected",
                event.trace_id,
                record.model_dump(mode="json"),
            )
            return self._result(record)

        await self.ledger.save(record)
        snapshot = SourceSnapshot(
            source_id=source_id,
            source_type=SourceType.INCIDENT_CASE,
            path=f"work-order-{event.work_order_id}.md",
            content=content,
            content_hash=content_hash,
            version=source_version,
            tenant_id=event.tenant_id,
            visibility="tenant",
            captured_at=event.completed_at,
        )
        result = await self.ingestion.ingest_snapshot(
            snapshot,
            metadata={
                "work_order_id": event.work_order_id,
                "work_order_version": event.work_order_version,
                "device_id": event.device_id,
                "device_category": sanitized.device_category,
                "device_model": sanitized.device_model,
                "knowledge_tags": sanitized.knowledge_tags,
                "completed_at": event.completed_at.isoformat(),
                "event_id": event.event_id,
                "schema_version": event.schema_version,
                "quality_score": assessment.score,
            },
            trace_id=event.trace_id,
        )
        record.status = WorkOrderKnowledgeStatus(result.status)
        record.chunks = result.chunks
        record.error = result.error
        record.updated_at = datetime.now(UTC)
        if record.status in {
            WorkOrderKnowledgeStatus.INDEXED,
            WorkOrderKnowledgeStatus.SKIPPED,
        }:
            record.indexed_at = record.updated_at
        await self.ledger.save(record)
        return self._result(record)

    async def get_status(self, event_id: str) -> WorkOrderKnowledgeRecord | None:
        return await self.ledger.get(event_id)

    async def revoke(self, tenant_id: str, work_order_id: str, reason: str) -> int:
        source_id = self.source_id(tenant_id, work_order_id)
        await self.catalog.deactivate(source_id)
        records = await self.ledger.revoke_source(source_id, reason)
        deleted = await self.index.delete_source(source_id)
        await self.trace.emit(
            "knowledge.work_order_revoked",
            records[-1].event_id if records else source_id,
            {"source_id": source_id, "reason": reason, "deleted_chunks": deleted},
        )
        return deleted

    @staticmethod
    def source_id(tenant_id: str, work_order_id: str) -> str:
        return f"work-order/{tenant_id}/{work_order_id}"

    @staticmethod
    def _result(record: WorkOrderKnowledgeRecord) -> WorkOrderKnowledgeIngestionResult:
        return WorkOrderKnowledgeIngestionResult(
            event_id=record.event_id,
            tenant_id=record.tenant_id,
            work_order_id=record.work_order_id,
            source_id=record.source_id,
            version=record.source_version,
            status=record.status,
            chunks=record.chunks,
            quality_score=record.quality_score,
            quality_issues=record.quality_issues,
            error=record.error,
        )

    @staticmethod
    def _content(event: WorkOrderCompletedEvent) -> str:
        root_cause = event.root_cause.strip() or "未明确记录"
        verification = event.verification_result.strip() or "历史工单未记录"
        replaced_parts = event.replaced_parts.strip() or "无"
        tags = "、".join(event.knowledge_tags) or "无"
        return (
            f"# 工单 {event.work_order_id} 维修案例\n\n"
            f"## 设备信息\n\n类别：{event.device_category or '未知'}\n\n"
            f"型号：{event.device_model or '未知'}\n\n"
            f"## 故障现象\n\n{event.description.strip()}\n\n"
            f"## 根因分析\n\n{root_cause}\n\n"
            f"## 处理过程\n\n{event.repair_process.strip()}\n\n"
            f"## 解决方案\n\n{event.solution.strip()}\n\n"
            f"## 修复验证\n\n{verification}\n\n"
            f"## 更换部件\n\n{replaced_parts}\n\n"
            f"## 标签\n\n{tags}\n"
        )
