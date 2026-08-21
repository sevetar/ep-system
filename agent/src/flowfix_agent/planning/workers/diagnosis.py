from __future__ import annotations

from pydantic import BaseModel, Field

from flowfix_agent.core.errors import FlowFixError
from flowfix_agent.core.models import RequestScope
from flowfix_agent.planning.models import Artifact, IncidentContext, TaskSpec
from flowfix_agent.planning.ports import DiagnosisEvidencePort, DiagnosisGeneratorPort
from flowfix_agent.retrieval.models import Evidence, RetrievalOptions


# 表示生成器输出格式非法或引用不合法，修复后仍失败。
class DiagnosisGenerationError(FlowFixError):
    pass


# 表示 Worker 兜底校验发现假设缺来源或引用编号非法。
class DiagnosisValidationError(FlowFixError):
    pass


# 单条根因假设：要点、正反证据、置信度与缺失信息。
class DiagnosisHypothesis(BaseModel):
    hypothesis_id: str
    title: str
    summary: str
    supporting_evidence: list[int] = Field(default_factory=list)
    opposing_evidence: list[int] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    missing_info: list[str] = Field(default_factory=list)


# 一次诊断的完整结果：总结论、总置信度、假设列表与缺失信息。
class DiagnosisResult(BaseModel):
    conclusion: str
    confidence: float = Field(ge=0, le=1)
    hypotheses: list[DiagnosisHypothesis] = Field(default_factory=list)
    missing_info: list[str] = Field(default_factory=list)
    # 新证据推翻先前假设时的修订说明；非空时触发 new_evidence 重规划。
    hypothesis_revised: str | None = None
    # 与影响评估等结论冲突的说明；非空时触发 artifact_conflict 重规划。
    conflict: str | None = None


# 只读 Diagnosis Worker：检索证据、生成假设并产出带来源的结构化 Artifact。
class DiagnosisWorker:
    worker_id = "diagnosis"

    # 注入证据检索与诊断生成器端口，限定单轮最大查询次数。
    def __init__(
        self,
        retrieval: DiagnosisEvidencePort,
        generator: DiagnosisGeneratorPort,
        *,
        max_queries: int = 3,
    ) -> None:
        self.retrieval = retrieval
        self.generator = generator
        self.max_queries = max_queries

    # 按任务执行诊断：推导查询、只读检索、生成并校验假设、产出 Artifact。
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
                trace_id=f"{incident.trace_id}:diag:{task.task_id}:{index}",
                chain="investigation",
                role="diagnosis-worker",
            )
            if not bundle.selected_evidence:
                empty_queries.append(query)
            all_evidence.extend(bundle.selected_evidence)

        # 每次检索的引用编号从 1 开始，合并前重排为全局 1..N，避免跨包编号冲突。
        reindexed = self._reindex(all_evidence)
        evidence_by_id = {item.citation_id: item for item in reindexed}

        if not reindexed:
            # 无证据时不调用生成器，fail-closed 直接拒答，防止模型常识补全。
            result = DiagnosisResult(
                conclusion="证据不足，无法给出根因假设。",
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
            "diagnosis": result.model_dump(mode="json"),
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

    # 兜底校验：每条假设必须有正证据来源且所有引用编号来自实际证据。
    @staticmethod
    def _validate_result(
        result: DiagnosisResult, evidence_by_id: dict[int, Evidence]
    ) -> None:
        allowed = set(evidence_by_id)
        for hypothesis in result.hypotheses:
            if not hypothesis.supporting_evidence:
                raise DiagnosisValidationError(
                    f"hypothesis lacks supporting evidence: {hypothesis.hypothesis_id}"
                )
            cited = set(hypothesis.supporting_evidence) | set(
                hypothesis.opposing_evidence
            )
            invalid = sorted(cited - allowed)
            if invalid:
                raise DiagnosisValidationError(
                    f"hypothesis cites unknown evidence ids: {invalid}"
                )

    # 按假设顺序收集去重的被引用编号。
    @staticmethod
    def _cited_ids(result: DiagnosisResult) -> list[int]:
        cited: list[int] = []
        for hypothesis in result.hypotheses:
            for citation_id in (
                hypothesis.supporting_evidence + hypothesis.opposing_evidence
            ):
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
