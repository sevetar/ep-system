from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from flowfix_agent.tools.models import ToolCall, ToolObservation


# 调查停止原因：完成、预算耗尽、证据不足、被阻断。
class StopReason(StrEnum):
    COMPLETED = "completed"
    BUDGET_EXHAUSTED = "budget_exhausted"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    BLOCKED = "blocked"


# 调查请求：事故、租户、目标、允许能力与最大步骤。
class InvestigationRequest(BaseModel):
    incident_id: str
    tenant_id: str
    thread_id: str
    goal: str
    trace_id: str
    allowed_capabilities: set[str]
    max_steps: int = Field(default=6, ge=1, le=12)


# Agent 单步决策：调用工具、得出结论、不确定性或停止原因。
class AgentDecision(BaseModel):
    tool_call: ToolCall | None = None
    conclusion: str | None = None
    uncertainty: list[str] = Field(default_factory=list)
    stop_reason: StopReason | None = None


# 调查结果：结论、观测、证据引用、不确定性、停止原因与步数。
class InvestigationResult(BaseModel):
    incident_id: str
    trace_id: str
    conclusion: str
    observations: list[ToolObservation]
    evidence_refs: list[str] = Field(default_factory=list)
    uncertainty: list[str] = Field(default_factory=list)
    stop_reason: StopReason
    steps: int
