from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from flowfix_agent.core.errors import FlowFixError
from flowfix_agent.core.models import RequestScope
from flowfix_agent.planning.models import Artifact, IncidentContext, TaskSpec
from flowfix_agent.planning.ports import (
    ResourcePlanningEvidencePort,
    ResourcePlanningGeneratorPort,
)
from flowfix_agent.retrieval.models import Evidence, RetrievalOptions


# 资源类型：人员、备件与窗口。
class ResourceKind(StrEnum):
    PERSONNEL = "personnel"
    SPARE_PART = "spare_part"
    WINDOW = "window"


# 表示生成器输出格式非法或引用不合法，修复后仍失败。
class ResourcePlanningGenerationError(FlowFixError):
    pass


# 表示 Worker 兜底校验发现候选/冲突/替代缺来源或引用编号非法。
class ResourcePlanningValidationError(FlowFixError):
    pass


# 单个资源候选：人员/备件/窗口，标记是否可用并带证据来源。
class ResourceCandidate(BaseModel):
    candidate_id: str
    kind: ResourceKind
    name: str
    description: str
    available: bool = True
    supporting_evidence: list[int] = Field(default_factory=list)


# 单条资源冲突：目标资源不可用或无法满足处置需求，带证据来源。
class ResourceConflict(BaseModel):
    conflict_id: str
    resource_id: str
    reason: str
    supporting_evidence: list[int] = Field(default_factory=list)


# 单条替代方案：针对冲突资源给出的替代候选，带证据来源。
class ResourceAlternative(BaseModel):
    alternative_id: str
    resource_id: str
    alternative_name: str
    description: str
    supporting_evidence: list[int] = Field(default_factory=list)


# 一次资源规划结果：主资源可用性、候选、冲突、替代方案、置信度与缺失信息。
class ResourcePlanningResult(BaseModel):
    primary_available: bool = False
    candidates: list[ResourceCandidate] = Field(default_factory=list)
    conflicts: list[ResourceConflict] = Field(default_factory=list)
    alternatives: list[ResourceAlternative] = Field(default_factory=list)
    confidence: float = Field(default=0, ge=0, le=1)
    missing_info: list[str] = Field(default_factory=list)


# 只读 ResourcePlanning Worker：检索资源证据，生成并校验候选/冲突/替代方案，产出带来源的 Artifact。
class ResourcePlanningWorker:
    worker_id = "resource_planning"

    # 注入资源规划证据检索及生成器端口，限定单轮最大查询次数。
    def __init__(
        self,
        retrieval: ResourcePlanningEvidencePort,
        generator: ResourcePlanningGeneratorPort,
        *,
        max_queries: int = 3,
    ) -> None:
        self.retrieval = retrieval
        self.generator = generator
        self.max_queries = max_queries

    # 按任务执行资源规划：推导查询、只读检索、生成并校验结果、产出含资源规划的 Artifact。
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
                trace_id=f"{incident.trace_id}:resource:{task.task_id}:{index}",
                chain="investigation",
                role="resource-planning-worker",
            )
            if not bundle.selected_evidence:
                empty_queries.append(query)
            all_evidence.extend(bundle.selected_evidence)

        # 每次检索的引用编号从 1 开始，合并前重排为全局 1..N，避免跨包编号冲突。
        reindexed = self._reindex(all_evidence)
        evidence_by_id = {item.citation_id: item for item in reindexed}

        if not reindexed:
            # 无证据时不调用生成器，fail-closed 直接产出未知拒答，防止模型常识补全或占用资源。
            result = ResourcePlanningResult(
                primary_available=False,
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
            "resource_planning": result.model_dump(mode="json"),
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

    # 兜底校验：候选/冲突/替代必须有正证据来源且所有引用编号来自实际证据。
    @staticmethod
    def _validate_result(
        result: ResourcePlanningResult, evidence_by_id: dict[int, Evidence]
    ) -> None:
        allowed = set(evidence_by_id)
        sections = {
            "candidate": result.candidates,
            "conflict": result.conflicts,
            "alternative": result.alternatives,
        }
        for section_name, items in sections.items():
            for item in items:
                if not item.supporting_evidence:
                    raise ResourcePlanningValidationError(
                        f"{section_name} lacks supporting evidence"
                    )
                invalid = sorted(set(item.supporting_evidence) - allowed)
                if invalid:
                    raise ResourcePlanningValidationError(
                        f"{section_name} cites unknown evidence ids: {invalid}"
                    )
        # 主资源不可用时必须同时给出冲突与替代方案，否则结果自相矛盾。
        if not result.primary_available and not (
            result.conflicts or result.alternatives
        ):
            raise ResourcePlanningValidationError(
                "unavailable resource requires conflicts and alternatives"
            )

    # 按候选、冲突、替代顺序收集去重的被引用编号。
    @staticmethod
    def _cited_ids(result: ResourcePlanningResult) -> list[int]:
        cited: list[int] = []
        for item in (*result.candidates, *result.conflicts, *result.alternatives):
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
