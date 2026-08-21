from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from flowfix_agent.dispatch.domain.models import DispatchRequest


# 枚举运行时允许调用的派单工具名称。
class ToolName(StrEnum):
    GET_WORK_ORDER_SNAPSHOT = "get_work_order_snapshot"
    LIST_ELIGIBLE_WORKERS = "list_eligible_workers"
    GET_WORKER_LOADS = "get_worker_loads"
    SEARCH_DISPATCH_POLICY = "search_dispatch_policy"
    CREATE_ASSIGNMENT = "create_assignment"
    GET_ASSIGNMENT_OUTCOME = "get_assignment_outcome"
    PUBLISH_DISPATCH_AUDIT = "publish_dispatch_audit"


# 表示派单写入请求的即时接收状态。
class AssignmentReceiptStatus(StrEnum):
    ACCEPTED = "accepted"
    ALREADY_APPLIED = "already_applied"
    VERSION_CONFLICT = "version_conflict"
    REJECTED = "rejected"


# 表示派单业务操作经核验后的最终状态。
class AssignmentOutcomeStatus(StrEnum):
    ASSIGNED = "assigned"
    PENDING = "pending"
    CONFLICT = "conflict"
    FAILED = "failed"
    NOT_FOUND = "not_found"


# 描述派单运行时从接收、审批到审计的执行状态。
class RuntimeStatus(StrEnum):
    RECEIVED = "received"
    SNAPSHOT_FROZEN = "snapshot_frozen"
    DECISION_READY = "decision_ready"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    DENIED = "denied"
    EXECUTING = "executing"
    VERIFIED = "verified"
    AUDITED = "audited"
    FAILED = "failed"


# 保存一次工具调用链共享的追踪、租户、权限和预算上下文。
class RequestContext(BaseModel):
    trace_id: str = Field(min_length=1, max_length=128)
    tenant_id: str = Field(min_length=1, max_length=128)
    event_id: str = Field(min_length=1, max_length=128)
    permissions: list[str] = Field(default_factory=list)
    deadline: datetime
    # 人工审批有效期独立于自动执行阶段 deadline；恢复时签发新的 deadline。
    approval_expires_at: datetime | None = None
    execution_timeout_seconds: int = Field(default=60, ge=1, le=300)
    max_tool_calls: int = Field(default=32, ge=1, le=256)

    # 清洗、去重并排序请求携带的权限集合。
    @field_validator("permissions")
    @classmethod
    def normalize_permissions(cls, value: list[str]) -> list[str]:
        return sorted({item.strip() for item in value if item.strip()})

    # 要求截止时间包含明确时区，避免跨时区比较产生歧义。
    @field_validator("deadline")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("deadline must be timezone-aware")
        return value

    @field_validator("approval_expires_at")
    @classmethod
    def require_approval_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("approval_expires_at must be timezone-aware")
        return value


# 定义向业务系统提交派单写入所需的完整幂等命令。
class AssignmentCommand(BaseModel):
    tenant_id: str
    event_id: str
    dispatch_id: str
    work_order_id: str
    worker_id: str
    expected_version: int = Field(ge=0)
    idempotency_key: str = Field(min_length=8, max_length=300)


# 表示业务系统接收派单命令后返回的即时回执。
class AssignmentReceipt(BaseModel):
    status: AssignmentReceiptStatus
    idempotency_key: str
    work_order_id: str
    worker_id: str | None = None
    observed_version: int | None = Field(default=None, ge=0)
    reason_code: str | None = None
    message: str


# 表示按幂等键查询得到的派单最终业务结果。
class AssignmentOutcome(BaseModel):
    status: AssignmentOutcomeStatus
    idempotency_key: str
    work_order_id: str
    assigned_worker_id: str | None = None
    work_order_version: int | None = Field(default=None, ge=0)
    reason_code: str | None = None
    message: str


# 表示只读策略搜索工具返回的一条可追溯证据。
class PolicyEvidence(BaseModel):
    evidence_id: str
    content: str
    source: str


# 保存人工审批结论、审核人、候选人员和审批原因。
class ApprovalDecision(BaseModel):
    approved: bool
    reviewer_id: str = Field(min_length=1, max_length=128)
    worker_id: str | None = None
    reason: str = Field(min_length=1, max_length=1000)

    # 保证批准操作必须明确选择一个工作人员。
    @model_validator(mode="after")
    def approved_requires_worker(self) -> ApprovalDecision:
        if self.approved and not self.worker_id:
            raise ValueError("approved decision requires worker_id")
        return self


# 记录一次工具调用的请求、结果、耗时、尝试次数和错误类型。
class ToolAuditEvent(BaseModel):
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    trace_id: str
    tenant_id: str
    event_id: str
    tool_name: ToolName
    attempt: int = Field(ge=1)
    success: bool
    duration_ms: float = Field(ge=0)
    request: dict[str, Any]
    response: dict[str, Any] | None = None
    error_type: str | None = None


# 向调用方返回派单线程的当前状态、中断信息和业务结果。
class RuntimeResult(BaseModel):
    thread_id: str
    status: RuntimeStatus
    interrupted: bool = False
    decision: dict[str, Any] | None = None
    assignment_outcome: AssignmentOutcome | None = None
    approval: ApprovalDecision | None = None
    errors: list[str] = Field(default_factory=list)
    approval_expires_at: datetime | None = None
    # 仅供进程内诊断和测试访问，所有序列化响应都排除完整 Graph state。
    state: dict[str, Any] = Field(default_factory=dict, exclude=True)


# 封装启动派单运行时所需的请求、工单标识和请求上下文。
class DispatchRuntimeInput(BaseModel):
    request: DispatchRequest
    work_order_id: str
    context: RequestContext
    # 强制人工审批开关：调查链建议必须为 True，即使决策可自动派单也进入 HITL。
    requires_approval: bool = False

    # 校验上下文与派单请求的事件和租户血缘保持一致。
    @model_validator(mode="after")
    def validate_lineage(self) -> DispatchRuntimeInput:
        if self.context.event_id != self.request.event_id:
            raise ValueError("context event_id must match dispatch request")
        if self.context.tenant_id != self.request.tenant_id:
            raise ValueError("context tenant_id must match dispatch request")
        return self


# 表示派单审计事件首次发布或幂等重复发布的结果。
class AuditPublishResult(BaseModel):
    status: Literal["published", "already_published"]
    dispatch_id: str
