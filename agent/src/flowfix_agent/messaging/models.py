from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from flowfix_agent.dispatch.domain.models import DispatchTrigger


class DispatchEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = Field(default="dispatch-request/v1", pattern=r"^dispatch-request/v1$")
    event_id: str = Field(min_length=1, max_length=128)
    dispatch_id: str = Field(min_length=1, max_length=128)
    tenant_id: str = Field(min_length=1, max_length=128)
    work_order_id: str = Field(min_length=1, max_length=128)
    trace_id: str = Field(min_length=1, max_length=128)
    trigger: DispatchTrigger = DispatchTrigger.OVERLOAD
    deadline_seconds: int = Field(default=60, ge=5, le=300)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class DispatchOutcomeEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = "dispatch-outcome/v1"
    event_id: str
    dispatch_id: str
    tenant_id: str
    trace_id: str
    thread_id: str
    status: str
    interrupted: bool
    errors: list[str] = Field(default_factory=list)
    assignment_outcome: dict | None = None
    completed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class WorkOrderCompletedEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = Field(
        default="work-order-completed/v2", pattern=r"^work-order-completed/v[12]$"
    )
    event_id: str = Field(min_length=1, max_length=128)
    tenant_id: str = Field(min_length=1, max_length=128)
    work_order_id: str = Field(min_length=1, max_length=128)
    work_order_version: int = Field(ge=0)
    device_id: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=10_000)
    repair_process: str = Field(min_length=1, max_length=20_000)
    solution: str = Field(min_length=1, max_length=20_000)
    root_cause: str = Field(default="", max_length=10_000)
    verification_result: str = Field(default="", max_length=10_000)
    replaced_parts: str = Field(default="", max_length=10_000)
    device_category: str = Field(default="", max_length=256)
    device_model: str = Field(default="", max_length=256)
    knowledge_tags: list[str] = Field(default_factory=list, max_length=30)
    completed_at: datetime
    trace_id: str = Field(min_length=1, max_length=128)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class WorkOrderKnowledgeOutcomeEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = "knowledge-ingestion-result/v1"
    event_id: str
    tenant_id: str
    work_order_id: str
    source_id: str
    source_version: str
    status: str
    chunks: int = 0
    quality_score: int = 0
    quality_issues: list[str] = Field(default_factory=list)
    error: str | None = None
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
