from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


# 工单在调度流程中的业务状态。
class WorkOrderStatus(StrEnum):
    PENDING_APPROVAL = "pending_approval"
    PENDING_DISPATCH = "pending_dispatch"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


# 工单优先级枚举。
class WorkOrderPriority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


# 发起调度请求的触发方式。
class DispatchTrigger(StrEnum):
    CLAIM_TIMEOUT = "claim_timeout"
    URGENT = "urgent"
    OVERLOAD = "overload"
    MANUAL = "manual"


# 调度决策流程的处理状态。
class DispatchStatus(StrEnum):
    RECEIVED = "received"
    VALIDATED = "validated"
    DECIDED = "decided"
    MANUAL = "manual"
    REJECTED = "rejected"
    FAILED = "failed"


# 调度决策的最终结果类型。
class DispatchOutcome(StrEnum):
    ASSIGN = "assign"
    MANUAL = "manual"
    REJECTED = "rejected"
    FAILED = "failed"


# 调度决策的风险等级。
class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


# 决策时使用的不可变工单数据快照。
class WorkOrderSnapshot(BaseModel):
    work_order_id: str = Field(min_length=1, max_length=128)
    tenant_id: str = Field(min_length=1, max_length=128)
    device_id: str = Field(min_length=1, max_length=128)
    region: str = Field(min_length=1, max_length=128)
    required_skills: list[str] = Field(min_length=1)
    priority: WorkOrderPriority = WorkOrderPriority.NORMAL
    status: WorkOrderStatus = WorkOrderStatus.PENDING_DISPATCH
    version: int = Field(ge=0)
    assigned_worker_id: str | None = None
    captured_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # 清洗技能名称并保证至少存在一个有效技能。
    @field_validator("required_skills")
    @classmethod
    def normalize_required_skills(cls, value: list[str]) -> list[str]:
        normalized = sorted({item.strip().lower() for item in value if item.strip()})
        if not normalized:
            raise ValueError("required_skills must contain at least one non-empty skill")
        return normalized


# 决策时使用的工作人员状态快照。
class WorkerSnapshot(BaseModel):
    worker_id: str = Field(min_length=1, max_length=128)
    tenant_id: str = Field(min_length=1, max_length=128)
    region: str = Field(min_length=1, max_length=128)
    skills: dict[str, float] = Field(min_length=1)
    shift_active: bool = True
    available: bool = True
    current_load: int = Field(ge=0)
    capacity: int = Field(gt=0)
    # Java v1 当前不提供距离与 SLA 指标；缺失值不会参与评分，也不会被伪造。
    distance_km: float | None = Field(default=None, ge=0)
    sla_readiness: float | None = Field(default=None, ge=0.0, le=1.0)
    captured_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # 规范化技能名称与熟练度，并校验熟练度取值范围。
    @field_validator("skills")
    @classmethod
    def normalize_skills(cls, value: dict[str, float]) -> dict[str, float]:
        normalized = {
            key.strip().lower(): float(level)
            for key, level in value.items()
            if key.strip()
        }
        if not normalized:
            raise ValueError("skills must contain at least one non-empty skill")
        invalid = [key for key, level in normalized.items() if not 0.0 <= level <= 1.0]
        if invalid:
            raise ValueError(f"skill proficiency must be within [0, 1]: {invalid}")
        return dict(sorted(normalized.items()))

    # 计算工作人员当前负载占容量的比例。
    @property
    def load_ratio(self) -> float:
        return self.current_load / self.capacity


# 一次调度计算的请求信息。
class DispatchRequest(BaseModel):
    dispatch_id: str = Field(min_length=1, max_length=128)
    event_id: str = Field(min_length=1, max_length=128)
    tenant_id: str = Field(min_length=1, max_length=128)
    trigger: DispatchTrigger = DispatchTrigger.OVERLOAD
    requested_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


# 记录一次调度状态流转及其原因。
class StateTransition(BaseModel):
    source: DispatchStatus | None
    target: DispatchStatus
    reason: str


# 记录被排除的候选工作人员及原因。
class CandidateExclusion(BaseModel):
    worker_id: str
    reasons: list[str] = Field(min_length=1)


# 保存候选工作人员的综合评分和排名明细。
class CandidateScore(BaseModel):
    worker_id: str
    total_score: float = Field(ge=0.0, le=1.0)
    components: dict[str, float]
    reasons: list[str] = Field(default_factory=list)
    rank: int = Field(ge=1)


# 保存调度决策执行过程中的完整状态。
class DispatchState(BaseModel):
    dispatch_id: str
    event_id: str
    tenant_id: str
    status: DispatchStatus = DispatchStatus.RECEIVED
    skill_id: str
    skill_version: str
    skill_content_hash: str
    input_fingerprint: str
    candidates: list[CandidateScore] = Field(default_factory=list)
    exclusions: list[CandidateExclusion] = Field(default_factory=list)
    selected_worker_id: str | None = None
    risk_level: RiskLevel | None = None
    reasons: list[str] = Field(default_factory=list)
    transitions: list[StateTransition] = Field(default_factory=list)
    error: str | None = None


# 表示可持久化和回放的最终调度决策。
class DispatchDecision(BaseModel):
    decision_id: str
    dispatch_id: str
    event_id: str
    tenant_id: str
    work_order_id: str
    work_order_version: int
    status: DispatchStatus
    outcome: DispatchOutcome
    selected_worker_id: str | None = None
    risk_level: RiskLevel
    skill_id: str
    skill_version: str
    skill_content_hash: str
    input_fingerprint: str
    decision_fingerprint: str
    candidates: list[CandidateScore] = Field(default_factory=list)
    exclusions: list[CandidateExclusion] = Field(default_factory=list)
    reasons: list[str] = Field(min_length=1)
    transitions: list[StateTransition] = Field(default_factory=list)
    decided_at: datetime
    external_execution_status: Literal["not_started"] = "not_started"

    # 校验决策结果与所选工作人员字段是否一致。
    @model_validator(mode="after")
    def validate_outcome(self) -> DispatchDecision:
        if self.outcome == DispatchOutcome.ASSIGN and not self.selected_worker_id:
            raise ValueError("assign outcome requires selected_worker_id")
        if self.outcome != DispatchOutcome.ASSIGN and self.selected_worker_id:
            raise ValueError("non-assign outcome cannot contain selected_worker_id")
        return self
