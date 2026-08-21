from __future__ import annotations

import platform
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from flowfix_agent.evaluation.common import (
    boolean_rate,
    load_jsonl_dataset,
    write_json_report,
)
from flowfix_agent.evaluation.completion import (
    DiagnosisImpactPlanner,
    ScenarioCleanDiagnosisGenerator,
    ScenarioCleanImpactGenerator,
)
from flowfix_agent.evaluation.impact_safety import (
    CannedEvidenceItem,
    CannedRetrieval,
    CapturingRetrievalProvider,
)
from flowfix_agent.evaluation.replanning import (
    ConflictPlanner,
    DiagnosisPlanner,
    ResourcePlanner,
    ScenarioDiagnosisGenerator,
    ScenarioResourceGenerator,
)
from flowfix_agent.knowledge.models import SourceType
from flowfix_agent.memory.task_artifact import SQLiteTaskArtifactStore
from flowfix_agent.planning.completion import CompletionGate
from flowfix_agent.planning.controller import PlanController
from flowfix_agent.planning.models import IncidentContext, PlanDraft, TaskSpec
from flowfix_agent.planning.registry import WorkerRegistry
from flowfix_agent.planning.replanning import RuleBasedReplanDetector, RuleBasedReplanner
from flowfix_agent.planning.runtime import PlanningRuntime
from flowfix_agent.planning.validation import PlanValidator
from flowfix_agent.planning.workers.diagnosis import DiagnosisWorker
from flowfix_agent.planning.workers.impact_safety import (
    ImpactSafetyWorker,
    RiskLevel,
)
from flowfix_agent.planning.workers.resource_planning import (
    ResourceAlternative,
    ResourceCandidate,
    ResourcePlanningResult,
    ResourcePlanningWorker,
)
from flowfix_agent.retrieval.models import Evidence
from flowfix_agent.tools import ToolGateway, ToolRegistry, ToolResolver
from flowfix_agent.tools.providers import (
    RetrievalCapabilityClient,
    knowledge_search_spec,
)


# 表示一条 Golden Set 评测用例：场景、期望状态/版本/提案与固定证据表。
class GoldenCase(BaseModel):
    case_id: str
    goal: str
    scenario: Literal[
        "basic",
        "with-resource",
        "replan-new-evidence",
        "replan-conflict",
        "replan-resource",
        "refusal-blocked",
        "high-risk-blocked",
        "uncovered-criterion",
        "recovery-failed-task",
    ]
    expected_status: Literal["completed", "awaiting_human"]
    expected_replan_count: int = Field(default=0, ge=0)
    expected_plan_version: int = Field(default=1, ge=1)
    expected_proposal: bool = False
    dispatch_target: str | None = None
    success_criteria: list[str] = Field(default_factory=list)
    max_queries: int = Field(default=3, ge=1, le=10)
    evidence: dict[str, list[CannedEvidenceItem]] = Field(default_factory=dict)


# 首次调用注入瞬时故障、后续调用恢复的诊断 Worker：验证失败任务经 Replan 恢复。
class FaultyOnceDiagnosisWorker:
    worker_id = "diagnosis"

    # 包装真实 DiagnosisWorker，首次执行直接抛错。
    def __init__(self, inner: DiagnosisWorker) -> None:
        self.inner = inner
        self.calls = 0

    # 首次调用注入故障，恢复后的调用委托内部 Worker 产出干净制品。
    async def execute(self, incident, task, dependency_artifacts, *, plan_version=1):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("injected transient worker failure")
        return await self.inner.execute(
            incident, task, dependency_artifacts, plan_version=plan_version
        )


# 固定 Planner：影响评估 → 诊断 → 资源规划（覆盖根因/影响/资源三类成功标准）。
class FullInvestigationPlanner:
    # 生成影响、诊断与依赖其结果的资源规划任务草稿。
    async def plan(self, incident):
        return PlanDraft(
            plan_id=f"plan-{incident.incident_id}",
            tasks=[
                TaskSpec(
                    task_id="impact",
                    description=incident.goal,
                    required_role="impact_safety",
                    allowed_capabilities={"knowledge.search"},
                ),
                TaskSpec(
                    task_id="diagnose",
                    description=incident.goal,
                    required_role="diagnosis",
                    dependencies=["impact"],
                    allowed_capabilities={"knowledge.search"},
                ),
                TaskSpec(
                    task_id="resource",
                    description=incident.goal,
                    required_role="resource_planning",
                    dependencies=["diagnose"],
                    allowed_capabilities={"knowledge.search"},
                ),
            ],
        )


# 使用通用 JSONL 加载器读取 Golden Set 评测数据集。
def load_golden_dataset(path: Path) -> list[GoldenCase]:
    return load_jsonl_dataset(path, GoldenCase, "planning golden")


# 在固定数据集上运行完整调查链场景并汇总质量门禁指标。
async def run_golden_evaluation(dataset_path: Path) -> dict:
    """只使用固定证据与确定性生成器，不访问真实模型或 ES。"""
    cases = load_golden_dataset(dataset_path)
    rows: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="flowfix-golden-eval-") as temp_dir:
        for case in cases:
            rows.append(await _run_case(case, Path(temp_dir)))
    passed = sum(row["passed"] for row in rows)
    read_only_preserved = all(row["read_only_preserved"] for row in rows)
    query_budget_respected = all(row["query_budget_respected"] for row in rows)
    safety_holds = [row["safety_holds"] for row in rows]
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "milestone": "D18",
        "dataset": str(dataset_path),
        "runtime": {"python": platform.python_version(), "external_services_used": []},
        "metrics": {
            "total": len(rows),
            "passed": passed,
            "scenario_pass_rate": round(passed / len(rows), 4),
            "replan_recovery_rate": boolean_rate(
                [row for row in rows if row["expected_replan_count"] > 0], "replan_ok"
            ),
            "safety_holds_rate": round(sum(safety_holds) / len(rows), 4),
        },
        "gate": {
            "passed": bool(
                passed == len(rows)
                and read_only_preserved
                and query_budget_respected
                and all(safety_holds)
            ),
            "criteria": {
                "scenario_pass_rate": 1.0,
                "safety_holds": True,
                "read_only_preserved": True,
                "query_budget_respected": True,
            },
        },
        "cases": rows,
    }


# 运行单个 Golden 用例：按场景装配真实 Worker、Replan 与完成门禁。
async def _run_case(case: GoldenCase, temp_dir: Path) -> dict:
    store = SQLiteTaskArtifactStore(temp_dir / f"{case.case_id}.db")
    provider = CapturingRetrievalProvider(CannedRetrieval(_build_table(case.evidence)))
    registry = ToolRegistry()
    registry.register(knowledge_search_spec(), provider)
    gateway = ToolGateway(ToolResolver(registry))
    retrieval = RetrievalCapabilityClient(gateway)
    workers = WorkerRegistry()
    planner = _assemble_scenario(case, workers, retrieval)
    runtime = PlanningRuntime(
        planner,
        PlanController(store, PlanValidator()),
        workers,
        store,
        RuleBasedReplanner(),
        RuleBasedReplanDetector(),
        CompletionGate(),
    )
    incident = IncidentContext(
        incident_id=case.case_id,
        tenant_id="tenant-eval",
        thread_id=f"thread-{case.case_id}",
        goal=case.goal,
        trace_id=f"eval-{case.case_id}",
        success_criteria=case.success_criteria,
        dispatch_target=case.dispatch_target,
    )
    result = await runtime.run(incident)
    return _evaluate_result(case, result, provider)


# 按场景装配 Worker 与 Planner；故障恢复场景包装首次失败 Worker。
def _assemble_scenario(case: GoldenCase, workers: WorkerRegistry, retrieval) -> object:
    max_queries = case.max_queries
    if case.scenario == "replan-new-evidence":
        workers.register(
            "diagnosis",
            DiagnosisWorker(
                retrieval,
                ScenarioDiagnosisGenerator(
                    {"hypothesis_revised": "新日志推翻了初始根因假设。"}
                ),
                max_queries=max_queries,
            ),
        )
        return DiagnosisPlanner()
    if case.scenario == "replan-conflict":
        # 冲突信号只由诊断标记触发，影响评估须用干净中风险制品以通过完成门禁。
        workers.register(
            "impact_safety",
            ImpactSafetyWorker(
                retrieval,
                ScenarioCleanImpactGenerator(
                    risk_level=RiskLevel.MEDIUM, with_safety=True
                ),
                max_queries=max_queries,
            ),
        )
        workers.register(
            "diagnosis",
            DiagnosisWorker(
                retrieval,
                ScenarioDiagnosisGenerator(
                    {"conflict": "诊断结论与影响评估结论相悖。"}
                ),
                max_queries=max_queries,
            ),
        )
        return ConflictPlanner()
    if case.scenario == "replan-resource":
        workers.register(
            "resource_planning",
            ResourcePlanningWorker(
                retrieval, ScenarioResourceGenerator(), max_queries=max_queries
            ),
        )
        return ResourcePlanner()
    if case.scenario == "recovery-failed-task":
        workers.register(
            "diagnosis",
            FaultyOnceDiagnosisWorker(
                DiagnosisWorker(
                    retrieval, ScenarioCleanDiagnosisGenerator(), max_queries=max_queries
                )
            ),
        )
        return DiagnosisPlanner()
    if case.scenario == "high-risk-blocked":
        workers.register(
            "diagnosis",
            DiagnosisWorker(
                retrieval, ScenarioCleanDiagnosisGenerator(), max_queries=max_queries
            ),
        )
        workers.register(
            "impact_safety",
            ImpactSafetyWorker(
                retrieval,
                ScenarioCleanImpactGenerator(
                    risk_level=RiskLevel.CRITICAL, with_safety=False
                ),
                max_queries=max_queries,
            ),
        )
        return DiagnosisImpactPlanner()
    if case.scenario == "with-resource":
        _register_clean_workers(workers, retrieval, max_queries, include_resource=True)
        return FullInvestigationPlanner()
    # basic / refusal-blocked / uncovered-criterion 只注册诊断与影响干净 Worker。
    _register_clean_workers(workers, retrieval, max_queries, include_resource=False)
    if case.scenario == "basic" or case.scenario == "uncovered-criterion":
        return DiagnosisImpactPlanner()
    return DiagnosisPlanner()


# 注册干净 Worker：诊断/影响（中风险带约束）必须；资源规划按需注册。
def _register_clean_workers(
    workers: WorkerRegistry,
    retrieval,
    max_queries: int,
    *,
    include_resource: bool = True,
) -> None:
    workers.register(
        "diagnosis",
        DiagnosisWorker(
            retrieval, ScenarioCleanDiagnosisGenerator(), max_queries=max_queries
        ),
    )
    workers.register(
        "impact_safety",
        ImpactSafetyWorker(
            retrieval,
            ScenarioCleanImpactGenerator(risk_level=RiskLevel.MEDIUM, with_safety=True),
            max_queries=max_queries,
        ),
    )
    if include_resource:
        workers.register(
            "resource_planning",
            ResourcePlanningWorker(
                retrieval,
                _CleanResourceGenerator(),
                max_queries=max_queries,
            ),
        )


# 确定性资源规划生成器：主资源始终可用，供 with-resource 场景使用。
class _CleanResourceGenerator:
    model = "deterministic"

    # 产出引用首个证据的可用候选。
    async def generate(self, incident, task, evidence):
        first = evidence[0].citation_id
        return ResourcePlanningResult(
            primary_available=True,
            confidence=0.8,
            candidates=[
                ResourceCandidate(
                    candidate_id="c1",
                    kind="spare_part",
                    name="电源模块",
                    description="仓库现有可用备件。",
                    available=True,
                    supporting_evidence=[first],
                )
            ],
            conflicts=[],
            alternatives=[
                ResourceAlternative(
                    alternative_id="a1",
                    resource_id="r1",
                    alternative_name="上代兼容备件",
                    description="接口兼容，可临时替代。",
                    supporting_evidence=[first],
                )
            ],
            missing_info=[],
        )


# 汇总单个用例的断言：状态/版本/提案、只读链路、查询预算与安全不变量。
def _evaluate_result(case, result, provider) -> dict:
    status_ok = result.status == case.expected_status
    replan_ok = result.replan_count == case.expected_replan_count
    version_ok = result.plan_version == case.expected_plan_version
    proposal_ok = (result.proposal is not None) == case.expected_proposal
    read_only_preserved = bool(provider.contexts) and all(
        context.chain == "investigation" and context.permissions == {"tool:read"}
        for context in provider.contexts
    )
    query_budget_respected = len(provider.contexts) <= (
        case.max_queries * len(result.artifacts)
    )
    # 完成态必须不携带拒答制品或未承认的高风险（完成门禁的安全不变量）。
    safety_holds = not (
        result.status == "completed"
        and (_refusal_present(result.artifacts) or _unacknowledged_risk(result.artifacts))
    )
    passed = (
        status_ok
        and replan_ok
        and version_ok
        and proposal_ok
        and read_only_preserved
        and query_budget_respected
        and safety_holds
    )
    return {
        "case_id": case.case_id,
        "scenario": case.scenario,
        "status": result.status,
        "expected_status": case.expected_status,
        "replan_count": result.replan_count,
        "expected_replan_count": case.expected_replan_count,
        "plan_version": result.plan_version,
        "expected_plan_version": case.expected_plan_version,
        "proposal_present": result.proposal is not None,
        "replan_ok": replan_ok,
        "read_only_preserved": read_only_preserved,
        "query_budget_respected": query_budget_respected,
        "safety_holds": safety_holds,
        "retrieval_calls": len(provider.contexts),
        "passed": passed,
    }


# 判断任一制品是证据不足的拒答。
def _refusal_present(artifacts) -> bool:
    from flowfix_agent.planning.completion import _refusal_reason

    return any(_refusal_reason(item) is not None for item in artifacts)


# 判断任一影响制品的高风险未被安全约束覆盖。
def _unacknowledged_risk(artifacts) -> bool:
    for item in artifacts:
        if item.worker_id != "impact_safety":
            continue
        impact = item.payload.get("impact_safety") or {}
        if impact.get("overall_risk_level") in {"high", "critical"} and not (
            impact.get("safety_constraints") or impact.get("mandatory_checks")
        ):
            return True
    return False


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


# 使用通用报告写入器保存 Golden Set 评测结果。
def write_golden_report(report: dict, path: Path) -> None:
    write_json_report(report, path)
