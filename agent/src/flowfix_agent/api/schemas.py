from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from flowfix_agent.assistant.models import AssistantExecution
from flowfix_agent.core.models import RequestScope
from flowfix_agent.dispatch.domain.models import DispatchTrigger
from flowfix_agent.dispatch.runtime.models import ApprovalDecision
from flowfix_agent.investigation.models import InvestigationRequest, InvestigationResult
from flowfix_agent.knowledge.models import (
    IngestionReport,
    SourceType,
    WorkOrderKnowledgeRecord,
)
from flowfix_agent.planning.models import (
    IncidentContext,
    PlanningHumanInput,
    PlanningResult,
)
from flowfix_agent.qa.models import QAResult
from flowfix_agent.retrieval.models import EvidenceBundle, RetrievalOptions


# 定义知识摄取接口接收的路径、来源类型和重建选项。
class IngestRequest(BaseModel):
    paths: list[str] = Field(default_factory=lambda: ["."])
    source_type: SourceType = SourceType.PLATFORM_DOC
    recreate_index: bool = False


# 向 API 调用方返回知识摄取报告。
class IngestResponse(IngestionReport):
    pass


# 定义检索接口的查询文本、访问范围和运行选项。
class RetrievalRequest(BaseModel):
    query: str = Field(min_length=2, max_length=2000)
    scope: RequestScope = Field(default_factory=RequestScope)
    options: RetrievalOptions = Field(default_factory=RetrievalOptions)


# 向 API 调用方返回完整证据包。
class RetrievalResponse(EvidenceBundle):
    pass


# 复用检索参数发起受证据约束的问答请求。
class QARequest(RetrievalRequest):
    thread_id: str | None = Field(default=None, min_length=1, max_length=128)
    end_conversation: bool = False


# 定义辅助路由接口的消息文本和可选线程 ID。
class AssistantRouteRequest(BaseModel):
    message: str = Field(min_length=2, max_length=4000)
    thread_id: str | None = Field(default=None, min_length=1, max_length=128)


# 定义统一入口执行请求：消息、会话身份、租户与可选访问范围。
class AssistantExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=2, max_length=4000)
    thread_id: str | None = Field(default=None, min_length=1, max_length=128)
    scope: RequestScope | None = None


# 向 API 调用方返回统一入口编排执行结果。
class AssistantExecuteResponse(AssistantExecution):
    pass


# 定义多 Agent 规划请求：事故上下文与可选的派单目标工单号。
class InvestigationPlanRequest(BaseModel):
    incident_id: str = Field(min_length=1, max_length=128)
    tenant_id: str = Field(min_length=1, max_length=128)
    thread_id: str = Field(min_length=1, max_length=128)
    goal: str = Field(min_length=2, max_length=4000)
    success_criteria: list[str] = Field(default_factory=list)
    max_tasks: int = Field(default=8, ge=1, le=30)
    max_parallel: int = Field(default=2, ge=1, le=8)
    dispatch_target: str | None = None


# 向 API 调用方返回多 Agent 规划结果。
class PlanningResponse(PlanningResult):
    pass


# 定义单 Agent 只读调查请求：允许能力与最大步骤。
class InvestigationRunRequest(BaseModel):
    incident_id: str = Field(min_length=1, max_length=128)
    tenant_id: str = Field(min_length=1, max_length=128)
    thread_id: str = Field(min_length=1, max_length=128)
    goal: str = Field(min_length=2, max_length=4000)
    allowed_capabilities: set[str] = Field(default_factory=set)
    max_steps: int | None = Field(default=None, ge=1, le=12)


# 向 API 调用方返回单 Agent 只读调查结果。
class InvestigationResponse(InvestigationResult):
    pass


# 将多 Agent 规划请求转换为规划运行时的内部事故上下文。
def plan_request_to_incident(payload: InvestigationPlanRequest, trace_id: str) -> IncidentContext:
    return IncidentContext(
        incident_id=payload.incident_id,
        tenant_id=payload.tenant_id,
        thread_id=payload.thread_id,
        goal=payload.goal,
        trace_id=trace_id,
        success_criteria=payload.success_criteria,
        max_tasks=payload.max_tasks,
        max_parallel=payload.max_parallel,
        dispatch_target=payload.dispatch_target,
    )


# 将单 Agent 调查请求转换为调查运行时的内部请求对象。
def run_request_to_investigation(
    payload: InvestigationRunRequest, trace_id: str, *, default_max_steps: int = 6
) -> InvestigationRequest:
    return InvestigationRequest(
        incident_id=payload.incident_id,
        tenant_id=payload.tenant_id,
        thread_id=payload.thread_id,
        goal=payload.goal,
        trace_id=trace_id,
        allowed_capabilities=payload.allowed_capabilities,
        max_steps=payload.max_steps or default_max_steps,
    )


# 向 API 调用方返回完整问答结果。
class QAResponse(QAResult):
    pass


# 描述服务及其外部依赖的健康状态。
class HealthResponse(BaseModel):
    status: str
    service: str
    dependencies: dict[str, str] = Field(default_factory=dict)


# 返回当前索引、知识源、分块和激活版本统计。
class KnowledgeStatusResponse(BaseModel):
    index: str
    sources: int
    chunks: int
    active_versions: dict[str, str]


class WorkOrderKnowledgeEventStatusResponse(WorkOrderKnowledgeRecord):
    pass


class WorkOrderKnowledgeRevokeRequest(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=2, max_length=1000)


class WorkOrderKnowledgeRevokeResponse(BaseModel):
    source_id: str
    status: str = "revoked"
    deleted_chunks: int = 0


# 定义受控派单启动请求：工单、派单事件、鉴权与权限范围。
class DispatchStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    work_order_id: str = Field(min_length=1, max_length=128)
    dispatch_id: str = Field(min_length=1, max_length=128)
    event_id: str = Field(min_length=1, max_length=128)
    trace_id: str = Field(min_length=1, max_length=64)
    trigger: DispatchTrigger = DispatchTrigger.OVERLOAD
    deadline_seconds: int = Field(default=30, ge=1, le=300)


# 定义恢复挂起派单的请求：携带人工审批决策。
class DispatchResumeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approved: bool
    worker_id: str | None = Field(default=None, max_length=128)
    reason: str = Field(min_length=1, max_length=1000)

    def to_approval(self, reviewer_id: str) -> ApprovalDecision:
        return ApprovalDecision(
            approved=self.approved,
            reviewer_id=reviewer_id,
            worker_id=self.worker_id,
            reason=self.reason,
        )


class PlanningResumeRequest(PlanningHumanInput):
    pass
