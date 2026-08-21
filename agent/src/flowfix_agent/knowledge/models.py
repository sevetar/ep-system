from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


# 枚举知识源支持的业务类型。
class SourceType(StrEnum):
    PLATFORM_DOC = "platform_doc"
    SOP = "sop"
    DEVICE_MANUAL = "device_manual"
    FAQ = "faq"
    INCIDENT_CASE = "incident_case"


# 表示某个原始知识文件在指定时刻的不可变快照。
class SourceSnapshot(BaseModel):
    source_id: str
    source_type: SourceType
    path: str
    content: str
    content_hash: str
    version: str
    tenant_id: str = "public"
    visibility: Literal["public", "tenant"] = "public"
    captured_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # 返回由来源标识和版本组成的唯一知识键。
    @property
    def knowledge_key(self) -> str:
        return f"{self.source_id}:{self.version}"


# 表示写入检索投影的版本化知识分块及其向量。
class KnowledgeChunk(BaseModel):
    chunk_id: str
    source_id: str
    source_type: SourceType
    source_version: str
    knowledge_key: str
    tenant_id: str
    visibility: Literal["public", "tenant"]
    title: str
    section_path: str = ""
    content: str
    content_hash: str
    position: int
    metadata: dict[str, Any] = Field(default_factory=dict)
    embedding: list[float]


# 记录一个知识源当前处于激活状态的索引版本。
class CatalogRecord(BaseModel):
    source_id: str
    source_type: SourceType
    active_version: str
    knowledge_key: str
    content_hash: str
    indexed_chunks: int
    tenant_id: str
    visibility: Literal["public", "tenant"]
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


# 描述单个知识源的一次摄取结果。
class SourceIngestionResult(BaseModel):
    source_id: str
    version: str
    status: Literal["indexed", "skipped", "rejected", "failed", "revoked"]
    chunks: int = 0
    error: str | None = None


# 汇总一次批量知识摄取的状态与计数。
class IngestionReport(BaseModel):
    trace_id: str
    index: str
    indexed_chunks: int
    skipped_sources: int
    failed_sources: int
    sources: list[SourceIngestionResult]


class WorkOrderKnowledgeStatus(StrEnum):
    PROCESSING = "processing"
    INDEXED = "indexed"
    SKIPPED = "skipped"
    REJECTED = "rejected"
    FAILED = "failed"
    REVOKED = "revoked"


class KnowledgeQualityAssessment(BaseModel):
    accepted: bool
    score: int = Field(ge=0, le=100)
    issues: list[str] = Field(default_factory=list)
    redacted_fields: list[str] = Field(default_factory=list)


class WorkOrderKnowledgeRecord(BaseModel):
    event_id: str
    tenant_id: str
    work_order_id: str
    work_order_version: int
    source_id: str
    source_version: str
    content_hash: str
    status: WorkOrderKnowledgeStatus
    quality_score: int = Field(default=0, ge=0, le=100)
    quality_issues: list[str] = Field(default_factory=list)
    redacted_fields: list[str] = Field(default_factory=list)
    chunks: int = 0
    attempts: int = 1
    error: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    indexed_at: datetime | None = None
    revoked_at: datetime | None = None
    revoke_reason: str | None = None


class WorkOrderKnowledgeIngestionResult(BaseModel):
    event_id: str
    tenant_id: str
    work_order_id: str
    source_id: str
    version: str
    status: WorkOrderKnowledgeStatus
    chunks: int = 0
    quality_score: int = Field(default=0, ge=0, le=100)
    quality_issues: list[str] = Field(default_factory=list)
    error: str | None = None
