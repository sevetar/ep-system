from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Protocol

from flowfix_agent.core.models import RequestScope
from flowfix_agent.planning.models import (
    Artifact,
    CommittedPlan,
    IncidentContext,
    PlanDraft,
    PlanPatch,
    ReplanTrigger,
    TaskSpec,
)
from flowfix_agent.retrieval.models import Evidence, EvidenceBundle, RetrievalOptions

if TYPE_CHECKING:
    from flowfix_agent.planning.workers.diagnosis import DiagnosisResult
    from flowfix_agent.planning.workers.impact_safety import ImpactSafetyResult
    from flowfix_agent.planning.workers.resource_planning import ResourcePlanningResult


# 规划端口：根据事故上下文生成计划草稿。
class PlannerPort(Protocol):
    async def plan(self, incident: IncidentContext) -> PlanDraft: ...


# 重规划端口：根据失败任务或内容触发器生成计划补丁。
class ReplannerPort(Protocol):
    async def replan(
        self,
        incident: IncidentContext,
        plan: CommittedPlan,
        failed_task_ids: list[str],
        *,
        trigger: ReplanTrigger | None = None,
    ) -> PlanPatch: ...


# 重规划检测端口：从当前版本制品中识别内容触发的重规划信号。
class ReplanDetectorPort(Protocol):
    async def detect(
        self,
        incident: IncidentContext,
        plan: CommittedPlan,
        statuses: dict[str, str],
        artifacts: Sequence[Artifact],
    ) -> ReplanTrigger | None: ...


# Worker 能力协议：按任务执行并返回制品。
class WorkerCapability(Protocol):
    worker_id: str

    async def execute(
        self,
        incident: IncidentContext,
        task: TaskSpec,
        dependency_artifacts: list[Artifact],
        *,
        plan_version: int = 1,
    ) -> Artifact: ...


# 诊断证据检索端口：只读返回证据包，调用方显式声明 investigation 链路角色。
class DiagnosisEvidencePort(Protocol):
    async def retrieve(
        self,
        query: str,
        scope: RequestScope,
        options: RetrievalOptions,
        trace_id: str | None = None,
        *,
        chain: str,
        role: str,
    ) -> EvidenceBundle: ...


# 诊断生成器端口：依据事故/任务与证据生成结构化诊断结果。
class DiagnosisGeneratorPort(Protocol):
    model: str

    async def generate(
        self,
        incident: IncidentContext,
        task: TaskSpec,
        evidence: Sequence[Evidence],
    ) -> DiagnosisResult: ...


# 影响与安全证据检索端口：只读返回证据包，调用方显式声明 investigation 链路角色。
class ImpactSafetyEvidencePort(Protocol):
    async def retrieve(
        self,
        query: str,
        scope: RequestScope,
        options: RetrievalOptions,
        trace_id: str | None = None,
        *,
        chain: str,
        role: str,
    ) -> EvidenceBundle: ...


# 影响与安全生成器端口：依据事故/任务与证据生成结构化影响与安全评估结果。
class ImpactSafetyGeneratorPort(Protocol):
    model: str

    async def generate(
        self,
        incident: IncidentContext,
        task: TaskSpec,
        evidence: Sequence[Evidence],
    ) -> ImpactSafetyResult: ...


# 资源规划证据检索端口：只读返回证据包，调用方显式声明 investigation 链路角色。
class ResourcePlanningEvidencePort(Protocol):
    async def retrieve(
        self,
        query: str,
        scope: RequestScope,
        options: RetrievalOptions,
        trace_id: str | None = None,
        *,
        chain: str,
        role: str,
    ) -> EvidenceBundle: ...


# 资源规划生成器端口：依据事故/任务与证据生成资源候选、冲突与替代方案评估结果。
class ResourcePlanningGeneratorPort(Protocol):
    model: str

    async def generate(
        self,
        incident: IncidentContext,
        task: TaskSpec,
        evidence: Sequence[Evidence],
    ) -> ResourcePlanningResult: ...
