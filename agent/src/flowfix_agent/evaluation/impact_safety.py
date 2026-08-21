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
from flowfix_agent.planning.workers.impact_safety import (
    RISK_ORDER,
    ImpactSafetyResult,
    ImpactSafetyWorker,
    ImpactScope,
    MandatoryCheck,
    RiskItem,
    RiskLevel,
    SafetyConstraint,
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


# 表示一条 ImpactSafety 评测用例：目标、成功标准、期望风险等级与固定证据表。
class ImpactSafetyEvaluationCase(BaseModel):
    case_id: str
    goal: str
    success_criteria: list[str] = Field(default_factory=list)
    max_queries: int = Field(default=3, ge=1, le=10)
    expected_min_risk_level: RiskLevel = RiskLevel.HIGH
    expected_min_scopes: int = Field(default=1, ge=0)
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


# 确定性生成器：按期望风险等级返回引用首个证据的合法评估结果。
class DeterministicImpactSafetyGenerator:
    model = "deterministic"

    # 配置期望风险等级与影响范围数量。
    def __init__(
        self, risk_level: RiskLevel = RiskLevel.HIGH, scopes: int = 1
    ) -> None:
        self.risk_level = risk_level
        self.scopes = scopes

    # 引用重排后的首个证据编号，产出影响范围、风险、约束与必选校验。
    async def generate(self, incident, task, evidence):
        first = evidence[0].citation_id
        severity = (
            RiskLevel.HIGH if self.risk_level is RiskLevel.UNKNOWN else self.risk_level
        )
        return ImpactSafetyResult(
            overall_risk_level=self.risk_level,
            confidence=0.8,
            impact_scopes=[
                ImpactScope(
                    scope_id=f"s{i}",
                    target=f"受影响目标 {i}",
                    description="故障导致该目标受影响。",
                    supporting_evidence=[first],
                )
                for i in range(1, self.scopes + 1)
            ],
            risks=[
                RiskItem(
                    risk_id="r1",
                    title="影响扩大化",
                    description="故障可能扩大影响范围。",
                    severity=severity,
                    supporting_evidence=[first],
                )
            ],
            safety_constraints=[
                SafetyConstraint(
                    constraint_id="c1",
                    action="禁止在未隔离受影响设备前直接处置。",
                    rationale="防止人身伤害与二次故障。",
                    supporting_evidence=[first],
                )
            ],
            mandatory_checks=[
                MandatoryCheck(
                    check_id="m1",
                    item="处置前确认受影响设备已安全隔离。",
                    supporting_evidence=[first],
                )
            ],
            missing_info=["现场巡检数据"],
        )


# 固定 Planner：每个事故只产出一条 impact_safety 任务。
class FakeImpactSafetyPlanner:
    # 根据事故目标生成影响与安全评估任务草稿。
    async def plan(self, incident):
        return PlanDraft(
            plan_id=f"plan-{incident.incident_id}",
            tasks=[
                TaskSpec(
                    task_id="impact",
                    description=incident.goal,
                    required_role="impact_safety",
                    allowed_capabilities={"knowledge.search"},
                )
            ],
        )


# 使用通用 JSONL 加载器读取 ImpactSafety 评测数据集。
def load_impact_safety_dataset(path: Path) -> list[ImpactSafetyEvaluationCase]:
    return load_jsonl_dataset(path, ImpactSafetyEvaluationCase, "impact_safety")


# 在固定数据集上运行 ImpactSafety Worker 并汇总质量门禁指标。
async def run_impact_safety_evaluation(dataset_path: Path) -> dict:
    """只使用固定证据与确定性生成器，不访问真实模型或 ES。"""
    cases = load_impact_safety_dataset(dataset_path)
    rows: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="flowfix-impact-eval-") as temp_dir:
        for case in cases:
            rows.append(await _run_case(case, Path(temp_dir)))
    passed = sum(row["passed"] for row in rows)
    impact_sourced_rate = boolean_rate(rows, "items_sourced")
    citation_valid_rate = boolean_rate(rows, "citations_valid")
    read_only_preserved = all(row["read_only_preserved"] for row in rows)
    query_budget_respected = all(row["query_budget_respected"] for row in rows)
    artifact_persisted = all(row["artifact_persisted"] for row in rows)
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "milestone": "D13",
        "dataset": str(dataset_path),
        "runtime": {"python": platform.python_version(), "external_services_used": []},
        "metrics": {
            "total": len(rows),
            "passed": passed,
            "scenario_pass_rate": round(passed / len(rows), 4),
            "impact_sourced_rate": impact_sourced_rate,
            "citation_valid_rate": citation_valid_rate,
        },
        "gate": {
            "passed": (
                passed == len(rows)
                and impact_sourced_rate == 1.0
                and citation_valid_rate == 1.0
                and read_only_preserved
                and query_budget_respected
                and artifact_persisted
            ),
            "criteria": {
                "scenario_pass_rate": 1.0,
                "impact_sourced_rate": 1.0,
                "citation_valid_rate": 1.0,
                "risk_not_lowered": True,
                "min_risk_respected": True,
                "fail_closed_preserved": True,
                "read_only_preserved": True,
                "query_budget_respected": True,
                "artifact_persisted": True,
            },
        },
        "cases": rows,
    }


# 运行单个评测用例：装配真实网关与 Worker，在 PlanningRuntime 中执行。
async def _run_case(case: ImpactSafetyEvaluationCase, temp_dir: Path) -> dict:
    store = SQLiteTaskArtifactStore(temp_dir / f"{case.case_id}.db")
    provider = CapturingRetrievalProvider(CannedRetrieval(_build_table(case.evidence)))
    registry = ToolRegistry()
    registry.register(knowledge_search_spec(), provider)
    generator = DeterministicImpactSafetyGenerator(
        risk_level=case.expected_min_risk_level, scopes=case.expected_min_scopes
    )
    worker = ImpactSafetyWorker(
        RetrievalCapabilityClient(ToolGateway(ToolResolver(registry))),
        generator,
        max_queries=case.max_queries,
    )
    workers = WorkerRegistry()
    workers.register("impact_safety", worker)
    runtime = PlanningRuntime(
        FakeImpactSafetyPlanner(),
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
        (item for item in result.artifacts if item.worker_id == "impact_safety"), None
    )
    impact = (
        ImpactSafetyResult.model_validate(artifact.payload["impact_safety"])
        if artifact is not None
        else None
    )
    items = (
        [
            *impact.impact_scopes,
            *impact.risks,
            *impact.safety_constraints,
            *impact.mandatory_checks,
        ]
        if impact
        else []
    )
    allowed_ids = {
        item["citation_id"] for item in (artifact.payload["evidence"] if artifact else [])
    }
    cited = {citation_id for item in items for citation_id in item.supporting_evidence}
    # 空列表视为无违规项；no-evidence 场景无需来源也视为通过。
    items_sourced = all(bool(item.supporting_evidence) for item in items)
    citations_valid = cited <= allowed_ids
    overall = impact.overall_risk_level if impact else RiskLevel.UNKNOWN
    max_severity = max(
        (RISK_ORDER[risk.severity] for risk in (impact.risks if impact else [])),
        default=0,
    )
    risk_not_lowered = RISK_ORDER[overall] >= max_severity
    min_risk_respected = RISK_ORDER[overall] >= RISK_ORDER[case.expected_min_risk_level]
    confidence_valid = impact is not None and 0 <= impact.confidence <= 1
    missing_info_present = bool(artifact and artifact.payload.get("missing_info"))
    scopes_covered = (
        len(impact.impact_scopes) >= case.expected_min_scopes if impact else False
    )
    # fail-closed 守恒：证据不足场景必须输出 unknown，证据充分场景不得误报 unknown。
    if case.expected_min_risk_level is RiskLevel.UNKNOWN:
        fail_closed_preserved = overall is RiskLevel.UNKNOWN
    else:
        fail_closed_preserved = overall is not RiskLevel.UNKNOWN
    read_only_preserved = bool(provider.contexts) and all(
        context.chain == "investigation"
        and context.role == "impact-safety-worker"
        and context.permissions == {"tool:read"}
        for context in provider.contexts
    )
    query_budget_respected = len(provider.contexts) <= case.max_queries
    persisted = store.list_plan(
        "tenant-eval", f"thread-{case.case_id}", f"plan-{case.case_id}"
    )
    artifact_persisted = any(record.kind == "artifact" for record in persisted)
    passed = (
        result.status == "completed"
        and scopes_covered
        and items_sourced
        and citations_valid
        and confidence_valid
        and missing_info_present
        and risk_not_lowered
        and min_risk_respected
        and fail_closed_preserved
        and read_only_preserved
        and query_budget_respected
        and artifact_persisted
    )
    return {
        "case_id": case.case_id,
        "status": result.status,
        "overall_risk_level": overall.value,
        "impact_scopes": len(impact.impact_scopes) if impact else 0,
        "items_sourced": items_sourced,
        "citations_valid": citations_valid,
        "risk_not_lowered": risk_not_lowered,
        "min_risk_respected": min_risk_respected,
        "fail_closed_preserved": fail_closed_preserved,
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


# 使用通用报告写入器保存 ImpactSafety 评测结果。
def write_impact_safety_report(report: dict, path: Path) -> None:
    write_json_report(report, path)
