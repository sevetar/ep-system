from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


# 四种确定性路由结果类型，表示请求应进入哪条链路。
class RouteType(StrEnum):
    KNOWLEDGE_QA = "KNOWLEDGE_QA"
    DIRECT_DISPATCH = "DIRECT_DISPATCH"
    INCIDENT_INVESTIGATION = "INCIDENT_INVESTIGATION"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"


# 从请求文本中提取的工单号与设备号等关键实体（incident_time 为预留字段）。
class ExtractedEntities(BaseModel):
    work_order_id: str | None = None
    device_id: str | None = None
    incident_time: str | None = None


# 路由决策结果，包含链路类型、置信度、原因、缺失字段和追踪信息。
class RouteDecision(BaseModel):
    route_type: RouteType
    confidence: float = Field(ge=0, le=1)
    reason_code: str
    extracted_entities: ExtractedEntities = Field(default_factory=ExtractedEntities)
    missing_fields: list[str] = Field(default_factory=list)
    thread_id: str | None = None
    trace_id: str
