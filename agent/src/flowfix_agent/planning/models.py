from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


# 任务执行状态：待执行、完成、失败、被取代。
class TaskStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    SUPERSEDED = "superseded"


# 监督节点可选的下一步动作。
class SupervisorAction(StrEnum):
    EXECUTE_BATCH = "execute_batch"
    REQUEST_REPLAN = "request_replan"
    AWAIT_HUMAN = "await_human"
    COMPLETE = "complete"
    FAIL = "fail"


class PlanningStatus(StrEnum):
    COMPLETED = "completed"
    AWAITING_HUMAN = "awaiting_human"
    FAILED = "failed"


# 人工补充合同：retry 把补充信息并入事故上下文并重跑原计划，cancel 明确终止。
class PlanningHumanInput(BaseModel):
    action: Literal["retry", "cancel"]
    information: str = Field(min_length=1, max_length=4000)


# 事故上下文：租户、目标、成功标准与任务/并行预算。
class IncidentContext(BaseModel):
    incident_id: str
    tenant_id: str
    thread_id: str
    goal: str
    trace_id: str
    device_id: str | None = None
    success_criteria: list[str] = Field(default_factory=list)
    max_tasks: int = Field(default=8, ge=1, le=30)
    max_parallel: int = Field(default=2, ge=1, le=8)
    # 目标工单号；非空表示调查完成后需生成 DispatchProposal 交给派单链路。
    dispatch_target: str | None = None


# 计划中的任务：职责角色、依赖与允许能力。
class TaskSpec(BaseModel):
    task_id: str
    description: str
    required_role: str
    dependencies: list[str] = Field(default_factory=list)
    allowed_capabilities: set[str] = Field(default_factory=set)


# 计划草稿：任务列表，提交前需通过校验。
class PlanDraft(BaseModel):
    plan_id: str
    tasks: list[TaskSpec]


# 已版本化提交的计划：草稿加版本号。
class CommittedPlan(PlanDraft):
    version: int


# Worker 产出的结构化制品：负载、证据引用与置信度。
class Artifact(BaseModel):
    artifact_id: str
    task_id: str
    plan_version: int
    worker_id: str
    payload: dict[str, Any]
    evidence_refs: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0, ge=0, le=1)


# 一次 Replan 的修改：新增任务、取消任务与期望计划版本。
class PlanPatch(BaseModel):
    add_tasks: list[TaskSpec] = Field(default_factory=list)
    cancel_task_ids: list[str] = Field(default_factory=list)
    expected_plan_version: int


# 调查完成后交给派单链路的处置建议；真实写入只能由 Dispatch 链路经 HITL 完成。
class DispatchProposal(BaseModel):
    proposal_id: str
    incident_id: str
    plan_id: str
    plan_version: int
    work_order_id: str
    proposed_action: str
    reason: str
    risk_level: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    requires_approval: bool = True
    # 生成时间戳：同一提案重复转交时作为稳定的请求时间，保证派单决策幂等重放。
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


# 内容触发的重规划信号：类型、原因与受影响任务。
class ReplanTrigger(BaseModel):
    trigger: Literal["new_evidence", "artifact_conflict", "resource_unavailable"]
    reason: str
    cancel_task_ids: list[str] = Field(default_factory=list)


# 规划运行的最终结果：状态、制品、报告、重规划次数与可选派单建议。
class PlanningResult(BaseModel):
    incident_id: str
    plan_id: str
    plan_version: int
    status: PlanningStatus
    artifacts: list[Artifact]
    report: str
    replan_count: int = 0
    proposal: DispatchProposal | None = None
    thread_id: str | None = None
    interrupted: bool = False
