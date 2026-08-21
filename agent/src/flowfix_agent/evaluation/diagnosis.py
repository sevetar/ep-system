from __future__ import annotations

import platform
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from flowfix_agent.evaluation.common import (
    boolean_rate,
    load_jsonl_dataset,
    write_json_report,
)
from flowfix_agent.knowledge.models import SourceType
from flowfix_agent.memory.task_artifact import SQLiteTaskArtifactStore
from flowfix_agent.planning.controller import PlanController
from flowfix_agent.planning.models import IncidentContext, PlanDraft, TaskSpec
from flowfix_agent.planning.registry import WorkerRegistry
from flowfix_agent.planning.runtime import PlanningRuntime
from flowfix_agent.planning.validation import PlanValidator
from flowfix_agent.planning.workers.diagnosis import (
    DiagnosisHypothesis,
    DiagnosisResult,
    DiagnosisWorker,
)
from flowfix_agent.retrieval.models import (
    Evidence,
    EvidenceBundle,
    RetrievalMode,
)
from flowfix_agent.tools import ToolGateway, ToolRegistry, ToolResolver
from flowfix_agent.tools.models import ToolContext
from flowfix_agent.tools.providers import (
    RetrievalCapabilityClient,
    RetrievalToolProvider,
    knowledge_search_spec,
)


# 描述一条固定知识证据，门禁内以确定性方式返回。
class CannedEvidenceItem(BaseModel):
    chunk_id: str
    title: str = ""
    section_path: str | None = None
    content: str


# 表示一条 Diagnosis 评测用例：目标、成功标准与固定证据表。
class DiagnosisEvaluationCase(BaseModel):
    case_id: str
    goal: str
    success_criteria: list[str] = Field(default_factory=list)
    max_queries: int = Field(default=3, ge=1, le=10)
    expected_min_hypotheses: int = Field(default=1, ge=0)
    evidence: dict[str, list[CannedEvidenceItem]] = Field(default_factory=dict)


# 确定性检索：按关键词返回固定证据，未知查询返回空包，不访问 ES。
class CannedRetrieval:
    def __init__(self, table: dict[str, list[Evidence]]) -> None:
        self.table = table

    # 命中首个关键词即返回对应证据，未命中返回空证据包。
    async def retrieve(self, query, scope, options, trace_id=None):
        matched: list[Evidence] = []
        for keyword, evidence in self.table.items():
            if keyword in query:
                matched = evidence
                break
        return EvidenceBundle(
            trace_id=trace_id or "canned",
            original_query=query,
            retrieval_query=query,
            mode=RetrievalMode.HYBRID,
            scope=scope,
            candidates=[],
            selected_evidence=matched,
            budget_used=0,
            sufficient=bool(matched),
            latency_ms=0.0,
        )


# 记录每次工具调用上下文，供只读链路断言使用。
class CapturingRetrievalProvider(RetrievalToolProvider):
    def __init__(self, retrieval) -> None:
        super().__init__(retrieval)
        self.contexts: list[ToolContext] = []

    # 记录上下文后交给父类执行真实调用。
    async def invoke(self, capability, arguments, context):
        self.contexts.append(context)
        return await super().invoke(capability, arguments, context)


# 确定性生成器：固定返回一条引用首个证据的合法假设。
class DeterministicDiagnosisGenerator:
    model = "deterministic"

    # 引用重排后的首个证据编号并附带缺失信息。
    async def generate(self, incident, task, evidence):
        first = evidence[0].citation_id
        return DiagnosisResult(
            conclusion="综合证据判断为组件故障。",
            confidence=0.8,
            hypotheses=[
                DiagnosisHypothesis(
                    hypothesis_id="h1",
                    title="组件故障",
                    summary="证据指向组件故障。",
                    supporting_evidence=[first],
                    opposing_evidence=[],
                    confidence=0.8,
                    missing_info=["现场工单数据"],
                )
            ],
            missing_info=["现场工单数据"],
        )


# 固定 Planner：每个事故只产出一条 diagnosis 任务。
class FakeDiagnosisPlanner:
    # 根据事故目标生成诊断任务草稿。
    async def plan(self, incident):
        return PlanDraft(
            plan_id=f"plan-{incident.incident_id}",
            tasks=[
                TaskSpec(
                    task_id="diagnose",
                    description=incident.goal,
                    required_role="diagnosis",
                    allowed_capabilities={"knowledge.search"},
                )
            ],
        )


# 使用通用 JSONL 加载器读取 Diagnosis 评测数据集。
def load_diagnosis_dataset(path: Path) -> list[DiagnosisEvaluationCase]:
    return load_jsonl_dataset(path, DiagnosisEvaluationCase, "diagnosis")


# 在固定数据集上运行 Diagnosis Worker 并汇总质量门禁指标。
async def run_diagnosis_evaluation(dataset_path: Path) -> dict:
    """只使用固定证据与确定性生成器，不访问真实模型或 ES。"""
    cases = load_diagnosis_dataset(dataset_path)
    rows: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="flowfix-diagnosis-eval-") as temp_dir:
        for case in cases:
            rows.append(await _run_case(case, Path(temp_dir)))
    passed = sum(row["passed"] for row in rows)
    hypothesis_source_rate = boolean_rate(rows, "hypotheses_sourced")
    citation_valid_rate = boolean_rate(rows, "citations_valid")
    read_only_preserved = all(row["read_only_preserved"] for row in rows)
    query_budget_respected = all(row["query_budget_respected"] for row in rows)
    artifact_persisted = all(row["artifact_persisted"] for row in rows)
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "milestone": "D12",
        "dataset": str(dataset_path),
        "runtime": {"python": platform.python_version(), "external_services_used": []},
        "metrics": {
            "total": len(rows),
            "passed": passed,
            "scenario_pass_rate": round(passed / len(rows), 4),
            "hypothesis_source_rate": hypothesis_source_rate,
            "citation_valid_rate": citation_valid_rate,
        },
        "gate": {
            "passed": (
                passed == len(rows)
                and hypothesis_source_rate == 1.0
                and citation_valid_rate == 1.0
                and read_only_preserved
                and query_budget_respected
                and artifact_persisted
            ),
            "criteria": {
                "scenario_pass_rate": 1.0,
                "hypothesis_source_rate": 1.0,
                "citation_valid_rate": 1.0,
                "read_only_preserved": True,
                "query_budget_respected": True,
                "artifact_persisted": True,
            },
        },
        "cases": rows,
    }


# 运行单个评测用例：装配真实网关与 Worker，在 PlanningRuntime 中执行。
async def _run_case(case: DiagnosisEvaluationCase, temp_dir: Path) -> dict:
    store = SQLiteTaskArtifactStore(temp_dir / f"{case.case_id}.db")
    provider = CapturingRetrievalProvider(CannedRetrieval(_build_table(case.evidence)))
    registry = ToolRegistry()
    registry.register(knowledge_search_spec(), provider)
    worker = DiagnosisWorker(
        RetrievalCapabilityClient(ToolGateway(ToolResolver(registry))),
        DeterministicDiagnosisGenerator(),
        max_queries=case.max_queries,
    )
    workers = WorkerRegistry()
    workers.register("diagnosis", worker)
    runtime = PlanningRuntime(
        FakeDiagnosisPlanner(),
        PlanController(store, PlanValidator()),
        workers,
        store,
    )
    incident = IncidentContext(
        incident_id=case.case_id,
        tenant_id="tenant-eval",
        thread_id=f"thread-{case.case_id}",
        goal=case.goal,
        trace_id=f"eval-{case.case_id}",
        success_criteria=case.success_criteria,
    )
    result = await runtime.run(incident)
    return _evaluate_result(case, result, provider, store)


# 汇总单个用例的断言并计算是否通过。
def _evaluate_result(case, result, provider, store) -> dict:
    artifact = next(
        (item for item in result.artifacts if item.worker_id == "diagnosis"), None
    )
    diagnosis = (
        DiagnosisResult.model_validate(artifact.payload["diagnosis"])
        if artifact is not None
        else None
    )
    hypotheses = diagnosis.hypotheses if diagnosis else []
    allowed_ids = {
        item["citation_id"] for item in (artifact.payload["evidence"] if artifact else [])
    }
    cited = {
        citation_id
        for hypothesis in hypotheses
        for citation_id in hypothesis.supporting_evidence + hypothesis.opposing_evidence
    }
    hypotheses_sourced = bool(hypotheses) and all(
        bool(hypothesis.supporting_evidence) for hypothesis in hypotheses
    )
    citations_valid = bool(cited) and cited <= allowed_ids
    confidence_valid = (
        diagnosis is not None
        and 0 <= diagnosis.confidence <= 1
        and all(0 <= hypothesis.confidence <= 1 for hypothesis in hypotheses)
    )
    missing_info_present = bool(artifact and artifact.payload.get("missing_info"))
    read_only_preserved = bool(provider.contexts) and all(
        context.chain == "investigation"
        and context.role == "diagnosis-worker"
        and context.permissions == {"tool:read"}
        for context in provider.contexts
    )
    query_budget_respected = len(provider.contexts) <= case.max_queries
    persisted = store.list_plan("tenant-eval", f"thread-{case.case_id}", f"plan-{case.case_id}")
    artifact_persisted = any(record.kind == "artifact" for record in persisted)
    passed = (
        result.status == "completed"
        and len(hypotheses) >= case.expected_min_hypotheses
        and hypotheses_sourced
        and citations_valid
        and confidence_valid
        and missing_info_present
        and read_only_preserved
        and query_budget_respected
        and artifact_persisted
    )
    return {
        "case_id": case.case_id,
        "status": result.status,
        "hypotheses": len(hypotheses),
        "evidence_refs": artifact.evidence_refs if artifact else [],
        "hypotheses_sourced": hypotheses_sourced,
        "citations_valid": citations_valid,
        "confidence_valid": confidence_valid,
        "missing_info_present": missing_info_present,
        "read_only_preserved": read_only_preserved,
        "query_budget_respected": query_budget_respected,
        "retrieval_calls": len(provider.contexts),
        "artifact_persisted": artifact_persisted,
        "passed": passed,
    }


# 将数据集证据表转换为固定关键词到证据列表的映射。
def _build_table(
    raw: dict[str, list[CannedEvidenceItem]],
) -> dict[str, list[Evidence]]:
    table: dict[str, list[Evidence]] = {}
    for keyword, items in raw.items():
        table[keyword] = [
            Evidence(
                citation_id=1,
                chunk_id=item.chunk_id,
                source_id=item.chunk_id,
                source_type=SourceType.PLATFORM_DOC,
                source_version="1.0.0",
                title=item.title,
                section_path=item.section_path or "",
                content=item.content,
                score=0.9,
                estimated_tokens=len(item.content),
            )
            for item in items
        ]
    return table


# 使用通用报告写入器保存 Diagnosis 评测结果。
def write_diagnosis_report(report: dict, path: Path) -> None:
    write_json_report(report, path)
