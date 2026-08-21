from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from flowfix_agent.dispatch.runtime.models import RuntimeResult
from flowfix_agent.investigation.models import InvestigationResult
from flowfix_agent.planning.models import PlanningResult
from flowfix_agent.qa.models import QAResult
from flowfix_agent.routing.models import RouteType


# 统一入口生命周期结局，禁止用“是否 interrupt”代替真实业务终态。
class AssistantOutcome(StrEnum):
    COMPLETED = "completed"
    REFUSED = "refused"
    FAILED = "failed"
    DENIED = "denied"
    NEEDS_INPUT = "needs_input"
    NEEDS_APPROVAL = "needs_approval"


# 调用方下一步动作合同：包含 continuation、输入结构、恢复入口和过期时间。
class NextAction(BaseModel):
    type: str
    continuation_id: str
    input_schema: dict = Field(default_factory=dict)
    resume_endpoint: str
    expires_at: str | None = None


# 统一入口单次执行的编排结果：路由类型、结局、命中的链路结果与缺失字段。
class AssistantExecution(BaseModel):
    route_type: RouteType
    trace_id: str
    outcome: AssistantOutcome
    message: str
    route_reason_code: str | None = None
    execution_mode: str | None = None
    qa: QAResult | None = None
    dispatch: RuntimeResult | None = None
    investigation: InvestigationResult | None = None
    planning: PlanningResult | None = None
    missing_fields: list[str] = Field(default_factory=list)
    next_action: NextAction | None = None
