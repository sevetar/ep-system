from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from flowfix_agent.core.errors import FlowFixError
from flowfix_agent.core.models import RequestScope
from flowfix_agent.planning.models import Artifact, IncidentContext, TaskSpec
from flowfix_agent.planning.ports import (
    ImpactSafetyEvidencePort,
    ImpactSafetyGeneratorPort,
)
from flowfix_agent.retrieval.models import Evidence, RetrievalOptions


# 风险等级：证据不足为 unknown，低/中/高/严重逐级升高。
class RiskLevel(StrEnum):
    UNKNOWN = "unknown"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# 风险等级排序权重，用于「整体风险不得低于已识别风险」的守恒校验（生成器与评测共用）。
RISK_ORDER = {
    RiskLevel.UNKNOWN: 0,
    RiskLevel.LOW: 1,
    RiskLevel.MEDIUM: 2,
    RiskLevel.HIGH: 3,
    RiskLevel.CRITICAL: 4,
}


# 表示生成器输出格式非法或引用不合法，修复后仍失败。
class ImpactSafetyGenerationError(FlowFixError):
    pass


# 表示 Worker 兜底校验发现影响项缺来源、引用非法或整体风险被降级。
class ImpactSafetyValidationError(FlowFixError):
    pass


# 单个影响范围条目：受影响目标、影响描述与证据来源。
class ImpactScope(BaseModel):
    scope_id: str
    target: str
    description: str
    supporting_evidence: list[int] = Field(default_factory=list)


# 单个风险条目：标题、描述、严重等级与证据来源。
class RiskItem(BaseModel):
    risk_id: str
    title: str
    description: str
    severity: RiskLevel = RiskLevel.MEDIUM
    supporting_evidence: list[int] = Field(default_factory=list)


# 单条安全约束：处置必须遵守的操作边界，附带理由与证据来源。
class SafetyConstraint(BaseModel):
    constraint_id: str
    action: str
    rationale: str
    supporting_evidence: list[int] = Field(default_factory=list)


# 单条必选校验项：处置前必须完成的检查，附带证据来源。
class MandatoryCheck(BaseModel):
    check_id: str
    item: str
    supporting_evidence: list[int] = Field(default_factory=list)


# 一次影响与安全评估的完整结果：整体风险等级、影响范围、风险、约束、必选校验与置信度。
class ImpactSafetyResult(BaseModel):
    overall_risk_level: RiskLevel = RiskLevel.UNKNOWN
    confidence: float = Field(default=0, ge=0, le=1)
    impact_scopes: list[ImpactScope] = Field(default_factory=list)
    risks: list[RiskItem] = Field(default_factory=list)
    safety_constraints: list[SafetyConstraint] = Field(default_factory=list)
    mandatory_checks: list[MandatoryCheck] = Field(default_factory=list)
    missing_info: list[str] = Field(default_factory=list)


# 只读 ImpactSafety Worker：检索影响证据，生成并校验影响/风险/约束/必选校验，产出带来源的 Artifact。
class ImpactSafetyWorker:
    worker_id = "impact_safety"

    # 注入影响与安全证据检索及生成器端口，限定单轮最大查询次数。
    def __init__(
        self,
        retrieval: ImpactSafetyEvidencePort,
        generator: ImpactSafetyGeneratorPort,
        *,
        max_queries: int = 3,
    ) -> None:
        self.retrieval = retrieval
        self.generator = generator
        self.max_queries = max_queries

    # 按任务执行影响与安全评估：推导查询、只读检索、生成并校验结果、产出 Artifact。
    async def execute(
        self,
        incident: IncidentContext,
        task: TaskSpec,
        dependency_artifacts: list[Artifact],
        *,
        plan_version: int = 1,
    ) -> Artifact:
        queries = self._derive_queries(incident, task)
        scope = RequestScope(
            tenant_id=incident.tenant_id,
            visibility="tenant" if incident.tenant_id != "public" else "public",
        )
        options = RetrievalOptions()
        all_evidence: list[Evidence] = []
        empty_queries: list[str] = []
        for index, query in enumerate(queries):
            bundle = await self.retrieval.retrieve(
                query,
                scope,
                options,
                # 附带 task_id，保证重规划复查任务用独立 trace_id，避免网关按 trace 累计预算拦截。
                trace_id=f"{incident.trace_id}:impact:{task.task_id}:{index}",
                chain="investigation",
                role="impact-safety-worker",
            )
            if not bundle.selected_evidence:
                empty_queries.append(query)
            all_evidence.extend(bundle.selected_evidence)

        # 每次检索的引用编号从 1 开始，合并前重排为全局 1..N，避免跨包编号冲突。
        reindexed = self._reindex(all_evidence)
        evidence_by_id = {item.citation_id: item for item in reindexed}

        if not reindexed:
            # 无证据时不调用生成器，fail-closed 直接输出 unknown，防止模型常识补全或擅自降风险。
            result = ImpactSafetyResult(
                overall_risk_level=RiskLevel.UNKNOWN,
                confidence=0,
                missing_info=list(queries),
            )
        else:
            result = await self.generator.generate(incident, task, reindexed)
            self._validate_result(result, evidence_by_id)
            empty_queries.extend(result.missing_info)

        missing_info = self._merge_missing(result.missing_info, empty_queries)
        cited_ids = self._cited_ids(result)
        evidence_refs = [
            evidence_by_id[citation_id].chunk_id
            for citation_id in cited_ids
            if citation_id in evidence_by_id
        ]
        payload = {
            "impact_safety": result.model_dump(mode="json"),
            "evidence": [item.model_dump(mode="json") for item in reindexed],
            "queries": queries,
            "evidence_count": len(reindexed),
            "missing_info": missing_info,
        }
        return Artifact(
            artifact_id=f"artifact-{task.task_id}",
            task_id=task.task_id,
            # 使用执行时的计划版本，保证 Replan 后制品归属正确版本。
            plan_version=plan_version,
            worker_id=self.worker_id,
            payload=payload,
            evidence_refs=evidence_refs,
            confidence=result.confidence,
        )

    # 从任务描述与成功标准推导检索查询，去重并按 max_queries 截断。
    def _derive_queries(self, incident: IncidentContext, task: TaskSpec) -> list[str]:
        queries: list[str] = []
        primary = (task.description or incident.goal or "").strip()
        if primary:
            queries.append(primary)
        for criterion in incident.success_criteria:
            candidate = criterion.strip()
            if candidate and candidate not in queries:
                queries.append(candidate)
        return queries[: self.max_queries]

    # 合并全部证据并按 chunk_id 去重后重排引用编号。
    @staticmethod
    def _reindex(evidence: list[Evidence]) -> list[Evidence]:
        reindexed: list[Evidence] = []
        seen_chunks: set[str] = set()
        for item in evidence:
            if item.chunk_id in seen_chunks:
                continue
            seen_chunks.add(item.chunk_id)
            reindexed.append(
                item.model_copy(update={"citation_id": len(reindexed) + 1})
            )
        return reindexed

    # 兜底校验：影响项必须有正证据来源、引用合法，且整体风险等级不得低于已识别风险（不能降风险）。
    @staticmethod
    def _validate_result(
        result: ImpactSafetyResult, evidence_by_id: dict[int, Evidence]
    ) -> None:
        allowed = set(evidence_by_id)
        sections = {
            "impact scope": result.impact_scopes,
            "risk": result.risks,
            "safety constraint": result.safety_constraints,
            "mandatory check": result.mandatory_checks,
        }
        for section_name, items in sections.items():
            for item in items:
                if not item.supporting_evidence:
                    raise ImpactSafetyValidationError(
                        f"{section_name} lacks supporting evidence"
                    )
                invalid = sorted(set(item.supporting_evidence) - allowed)
                if invalid:
                    raise ImpactSafetyValidationError(
                        f"{section_name} cites unknown evidence ids: {invalid}"
                    )
        # 风险守恒：整体等级不能低于任一已识别风险的最高等级，否则视为擅自降风险。
        max_severity = max(
            (RISK_ORDER[risk.severity] for risk in result.risks), default=0
        )
        if RISK_ORDER[result.overall_risk_level] < max_severity:
            raise ImpactSafetyValidationError(
                "overall risk level must not be lower than the highest identified risk"
            )

    # 按影响范围、风险、约束与必选校验顺序收集去重的被引用编号。
    @staticmethod
    def _cited_ids(result: ImpactSafetyResult) -> list[int]:
        cited: list[int] = []
        for item in (
            *result.impact_scopes,
            *result.risks,
            *result.safety_constraints,
            *result.mandatory_checks,
        ):
            for citation_id in item.supporting_evidence:
                if citation_id not in cited:
                    cited.append(citation_id)
        return cited

    # 合并生成器缺失信息与空结果查询，去重保序。
    @staticmethod
    def _merge_missing(model_missing: list[str], empty_queries: list[str]) -> list[str]:
        merged: list[str] = []
        for item in [*model_missing, *empty_queries]:
            candidate = item.strip()
            if candidate and candidate not in merged:
                merged.append(candidate)
        return merged
