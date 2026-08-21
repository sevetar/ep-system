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
from flowfix_agent.evaluation.impact_safety import (
    CannedEvidenceItem,
    CannedRetrieval,
    CapturingRetrievalProvider,
)
from flowfix_agent.knowledge.models import SourceType
from flowfix_agent.memory.task_artifact import SQLiteTaskArtifactStore
from flowfix_agent.planning.completion import CompletionGate, WritePolicy
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
from flowfix_agent.planning.workers.impact_safety import (
    ImpactSafetyResult,
    ImpactSafetyWorker,
    ImpactScope,
    RiskLevel,
    SafetyConstraint,
)
from flowfix_agent.retrieval.models import Evidence
from flowfix_agent.tools import ToolGateway, ToolRegistry, ToolResolver
from flowfix_agent.tools.providers import (
    RetrievalCapabilityClient,
    knowledge_search_spec,
)


# 表示一条完成门禁评测用例：场景、期望状态、期望提案与固定证据表。
class CompletionEvaluationCase(BaseModel):
    case_id: str
    goal: str
    scenario: Literal["all-good", "refusal", "high-risk", "uncovered-criterion"]
    expected_status: Literal["completed", "awaiting_human"]
    expected_proposal: bool = False
    dispatch_target: str | None = None
    success_criteria: list[str] = Field(default_factory=list)
    max_queries: int = Field(default=3, ge=1, le=10)
    evidence: dict[str, list[CannedEvidenceItem]] = Field(default_factory=dict)


# 确定性诊断生成器：固定返回干净诊断，引用重排后的首个证据编号。
class ScenarioCleanDiagnosisGenerator:
    model = "deterministic"

    # 产出根因结论与一条带证据来源的假设。
    async def generate(self, incident, task, evidence):
        first = evidence[0].citation_id
        return DiagnosisResult(
            conclusion="电源模块老化导致停机",
            confidence=0.8,
            hypotheses=[
                DiagnosisHypothesis(
                    hypothesis_id="h1",
                    title="电源模块老化",
                    summary="依据设备日志与维护记录推断的根因。",
                    supporting_evidence=[first],
                    opposing_evidence=[],
                    confidence=0.8,
                )
            ],
            missing_info=[],
        )


# 确定性影响评估生成器：可配置风险等级与是否附带安全约束。
class ScenarioCleanImpactGenerator:
    model = "deterministic"

    # 配置默认风险等级与是否附带安全约束。
    def __init__(
        self,
        risk_level: RiskLevel = RiskLevel.MEDIUM,
        with_safety: bool = True,
    ) -> None:
        self.risk_level = risk_level
        self.with_safety = with_safety

    # 产出引用首个证据的影响范围，按配置附加安全约束。
    async def generate(self, incident, task, evidence):
        first = evidence[0].citation_id
        result = ImpactSafetyResult(
            overall_risk_level=self.risk_level,
            confidence=0.9,
            impact_scopes=[
                ImpactScope(
                    scope_id="s1",
                    target="下游产线",
                    description="停机将导致下游产线停摆。",
                    supporting_evidence=[first],
                )
            ],
        )
        if self.with_safety:
            result.safety_constraints = [
                SafetyConstraint(
                    constraint_id="c1",
                    action="禁止带电作业",
                    rationale="防止触电与短路扩大故障。",
                    supporting_evidence=[first],
                )
            ]
        return result


# 固定 Planner：单条诊断任务（拒答场景的基础任务）。
class DiagnosisPlanner:
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


# 固定 Planner：影响评估 → 诊断（完整调查链：先评估影响，再诊断根因）。
class DiagnosisImpactPlanner:
    # 生成影响任务与依赖其结果的诊断任务草稿。
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
            ],
        )


# 使用通用 JSONL 加载器读取完成门禁评测数据集。
def load_completion_dataset(path: Path) -> list[CompletionEvaluationCase]:
    return load_jsonl_dataset(path, CompletionEvaluationCase, "completion")


# 在固定数据集上运行完成门禁场景并汇总质量门禁指标。
async def run_completion_evaluation(dataset_path: Path) -> dict:
    """只使用固定证据与确定性生成器，不访问真实模型或 ES。"""
    cases = load_completion_dataset(dataset_path)
    rows: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="flowfix-completion-eval-") as temp_dir:
        for case in cases:
            rows.append(await _run_case(case, Path(temp_dir)))
    passed = sum(row["passed"] for row in rows)
    gate_decision_rate = boolean_rate(rows, "gate_decision_ok")
    proposal_quality_rate = boolean_rate(rows, "proposal_ok")
    read_only_preserved = all(row["read_only_preserved"] for row in rows)
    query_budget_respected = all(row["query_budget_respected"] for row in rows)
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "milestone": "D16",
        "dataset": str(dataset_path),
        "runtime": {"python": platform.python_version(), "external_services_used": []},
        "metrics": {
            "total": len(rows),
            "passed": passed,
            "scenario_pass_rate": round(passed / len(rows), 4),
            "gate_decision_rate": gate_decision_rate,
            "proposal_quality_rate": proposal_quality_rate,
        },
        "gate": {
            "passed": (
                passed == len(rows)
                and gate_decision_rate == 1.0
                and proposal_quality_rate == 1.0
                and read_only_preserved
                and query_budget_respected
            ),
            "criteria": {
                "scenario_pass_rate": 1.0,
                "gate_decision_rate": 1.0,
                "proposal_quality_rate": 1.0,
                "read_only_preserved": True,
                "query_budget_respected": True,
            },
        },
        "cases": rows,
    }


# 运行单个评测用例：按场景装配真实 Worker 与完成门禁。
async def _run_case(case: CompletionEvaluationCase, temp_dir: Path) -> dict:
    store = SQLiteTaskArtifactStore(temp_dir / f"{case.case_id}.db")
    provider = CapturingRetrievalProvider(CannedRetrieval(_build_table(case.evidence)))
    registry = ToolRegistry()
    registry.register(knowledge_search_spec(), provider)
    gateway = ToolGateway(ToolResolver(registry))
    retrieval = RetrievalCapabilityClient(gateway)
    workers = WorkerRegistry()
    if case.scenario == "refusal":
        # 拒答场景：证据表为空，Worker fail-closed 产出拒答制品，门禁必须转人工。
        workers.register(
            "diagnosis",
            DiagnosisWorker(
                retrieval, ScenarioCleanDiagnosisGenerator(), max_queries=case.max_queries
            ),
        )
        planner = DiagnosisPlanner()
    else:
        impact = ScenarioCleanImpactGenerator(
            risk_level=(
                RiskLevel.CRITICAL if case.scenario == "high-risk" else RiskLevel.MEDIUM
            ),
            # 高风险场景必须不附安全约束，才能验证门禁的「未承认风险」拦截。
            with_safety=case.scenario != "high-risk",
        )
        workers.register(
            "impact_safety",
            ImpactSafetyWorker(retrieval, impact, max_queries=case.max_queries),
        )
        workers.register(
            "diagnosis",
            DiagnosisWorker(
                retrieval, ScenarioCleanDiagnosisGenerator(), max_queries=case.max_queries
            ),
        )
        planner = DiagnosisImpactPlanner()
    runtime = PlanningRuntime(
        planner,
        PlanController(store, PlanValidator()),
        workers,
        store,
        completion_gate=CompletionGate(),
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


# 汇总单个用例的断言：门禁决策、提案只读性、只读链路与查询预算守恒。
def _evaluate_result(case, result, provider) -> dict:
    gate_decision_ok = result.status == case.expected_status
    proposal_present = result.proposal is not None
    proposal_expected = proposal_present == case.expected_proposal
    proposal_valid = True
    if proposal_present:
        # WritePolicy 防线：生成的提案必须只读、有证据且要求人工审批。
        proposal_valid = WritePolicy.validate_proposal(result.proposal) == []
    read_only_preserved = bool(provider.contexts) and all(
        context.chain == "investigation" and context.permissions == {"tool:read"}
        for context in provider.contexts
    )
    # 每个已完成任务最多 max_queries 次检索，总调用数不得超过任务数 × 预算。
    query_budget_respected = len(provider.contexts) <= (
        case.max_queries * len(result.artifacts)
    )
    passed = (
        gate_decision_ok
        and proposal_expected
        and proposal_valid
        and read_only_preserved
        and query_budget_respected
    )
    return {
        "case_id": case.case_id,
        "scenario": case.scenario,
        "status": result.status,
        "expected_status": case.expected_status,
        "proposal_present": proposal_present,
        "proposal_expected": case.expected_proposal,
        "gate_decision_ok": gate_decision_ok,
        "proposal_ok": proposal_expected and proposal_valid,
        "read_only_preserved": read_only_preserved,
        "query_budget_respected": query_budget_respected,
        "retrieval_calls": len(provider.contexts),
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


# 使用通用报告写入器保存完成门禁评测结果。
def write_completion_report(report: dict, path: Path) -> None:
    write_json_report(report, path)
