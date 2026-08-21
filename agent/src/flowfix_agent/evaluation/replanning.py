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
from flowfix_agent.planning.controller import PlanController
from flowfix_agent.planning.models import IncidentContext, PlanDraft, TaskSpec
from flowfix_agent.planning.registry import WorkerRegistry
from flowfix_agent.planning.replanning import RuleBasedReplanDetector, RuleBasedReplanner
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
)
from flowfix_agent.planning.workers.resource_planning import (
    ResourceAlternative,
    ResourceCandidate,
    ResourceConflict,
    ResourceKind,
    ResourcePlanningResult,
    ResourcePlanningWorker,
)
from flowfix_agent.retrieval.models import Evidence
from flowfix_agent.tools import ToolGateway, ToolRegistry, ToolResolver
from flowfix_agent.tools.providers import (
    RetrievalCapabilityClient,
    knowledge_search_spec,
)


# 表示一条 Replan 评测用例：事故目标、期望触发类型与期望计划版本。
class ReplanningEvaluationCase(BaseModel):
    case_id: str
    goal: str
    expected_trigger: Literal[
        "new_evidence", "artifact_conflict", "resource_unavailable"
    ]
    expected_plan_version: int = Field(default=2, ge=1)
    max_queries: int = Field(default=3, ge=1, le=10)
    evidence: dict[str, list[CannedEvidenceItem]] = Field(default_factory=dict)


# 确定性诊断生成器：首次调用携带触发标记，重规划后的调用输出干净结果。
class ScenarioDiagnosisGenerator:
    model = "deterministic"

    # 保存内容触发标记并记录调用次数。
    def __init__(self, marker: dict) -> None:
        self.marker = marker
        self.calls = 0

    # 按调用次序决定是否携带标记，引用重排后的首个证据编号。
    async def generate(self, incident, task, evidence):
        first = evidence[0].citation_id
        hypothesis_revised = None
        conflict = None
        if self.calls == 0:
            hypothesis_revised = self.marker.get("hypothesis_revised")
            conflict = self.marker.get("conflict")
        self.calls += 1
        return DiagnosisResult(
            conclusion="根因假设",
            confidence=0.8,
            hypotheses=[
                DiagnosisHypothesis(
                    hypothesis_id="h1",
                    title="根因假设",
                    summary="依据证据推断的根因。",
                    supporting_evidence=[first],
                    opposing_evidence=[],
                    confidence=0.8,
                )
            ],
            missing_info=[],
            hypothesis_revised=hypothesis_revised,
            conflict=conflict,
        )


# 确定性影响评估生成器：固定返回高风险结论，供诊断冲突场景作依赖。
class ScenarioImpactGenerator:
    model = "deterministic"

    # 产出固定 critical 影响结论。
    async def generate(self, incident, task, evidence):
        first = evidence[0].citation_id
        return ImpactSafetyResult(
            overall_risk_level=RiskLevel.CRITICAL,
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


# 确定性资源规划生成器：首次调用主资源不可用，重规划后的调用返回可用。
class ScenarioResourceGenerator:
    model = "deterministic"

    # 初始化调用计数器。
    def __init__(self) -> None:
        self.calls = 0

    # 按调用次序决定主资源可用性，引用首个证据编号。
    async def generate(self, incident, task, evidence):
        first = evidence[0].citation_id
        available = self.calls > 0
        self.calls += 1
        return ResourcePlanningResult(
            primary_available=available,
            confidence=0.8,
            candidates=[
                ResourceCandidate(
                    candidate_id="c1",
                    kind=ResourceKind.SPARE_PART,
                    name="电源模块",
                    description="备件供应说明。",
                    available=available,
                    supporting_evidence=[first],
                )
            ],
            conflicts=(
                []
                if available
                else [
                    ResourceConflict(
                        conflict_id="cf1",
                        resource_id="r1",
                        reason="关键备件库存在途未到。",
                        supporting_evidence=[first],
                    )
                ]
            ),
            alternatives=(
                []
                if available
                else [
                    ResourceAlternative(
                        alternative_id="a1",
                        resource_id="r1",
                        alternative_name="上代兼容备件",
                        description="接口兼容，可临时替代。",
                        supporting_evidence=[first],
                    )
                ]
            ),
            missing_info=[] if available else ["备件到货时间"],
        )


# 固定 Planner：单条诊断任务（新证据场景的基础任务）。
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


# 固定 Planner：单条资源规划任务。
class ResourcePlanner:
    # 根据事故目标生成资源规划任务草稿。
    async def plan(self, incident):
        return PlanDraft(
            plan_id=f"plan-{incident.incident_id}",
            tasks=[
                TaskSpec(
                    task_id="resource",
                    description=incident.goal,
                    required_role="resource_planning",
                    allowed_capabilities={"knowledge.search"},
                )
            ],
        )


# 固定 Planner：影响评估 → 诊断（先评估影响，再诊断根因并核对一致性）。
class ConflictPlanner:
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


# 使用通用 JSONL 加载器读取 Replan 评测数据集。
def load_replanning_dataset(path: Path) -> list[ReplanningEvaluationCase]:
    return load_jsonl_dataset(path, ReplanningEvaluationCase, "replanning")


# 在固定数据集上运行三类 Replan 场景并汇总质量门禁指标。
async def run_replanning_evaluation(dataset_path: Path) -> dict:
    """只使用固定证据与确定性生成器，不访问真实模型或 ES。"""
    cases = load_replanning_dataset(dataset_path)
    rows: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="flowfix-replan-eval-") as temp_dir:
        for case in cases:
            rows.append(await _run_case(case, Path(temp_dir)))
    passed = sum(row["passed"] for row in rows)
    trigger_rate = boolean_rate(rows, "expected_trigger_detected")
    version_commit_rate = boolean_rate(rows, "version_committed")
    read_only_preserved = all(row["read_only_preserved"] for row in rows)
    query_budget_respected = all(row["query_budget_respected"] for row in rows)
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "milestone": "D15",
        "dataset": str(dataset_path),
        "runtime": {"python": platform.python_version(), "external_services_used": []},
        "metrics": {
            "total": len(rows),
            "passed": passed,
            "scenario_pass_rate": round(passed / len(rows), 4),
            "expected_trigger_detected_rate": trigger_rate,
            "atomic_version_commit_rate": version_commit_rate,
        },
        "gate": {
            "passed": (
                passed == len(rows)
                and trigger_rate == 1.0
                and version_commit_rate == 1.0
                and read_only_preserved
                and query_budget_respected
            ),
            "criteria": {
                "scenario_pass_rate": 1.0,
                "expected_trigger_detected_rate": 1.0,
                "atomic_version_commit_rate": 1.0,
                "replan_count_exact": 1,
                "read_only_preserved": True,
                "query_budget_respected": True,
            },
        },
        "cases": rows,
    }


# 运行单个评测用例：按期望触发器装配真实 Worker 与 Replan 控制面。
async def _run_case(case: ReplanningEvaluationCase, temp_dir: Path) -> dict:
    store = SQLiteTaskArtifactStore(temp_dir / f"{case.case_id}.db")
    provider = CapturingRetrievalProvider(CannedRetrieval(_build_table(case.evidence)))
    registry = ToolRegistry()
    registry.register(knowledge_search_spec(), provider)
    gateway = ToolGateway(ToolResolver(registry))
    retrieval = RetrievalCapabilityClient(gateway)
    workers = WorkerRegistry()
    if case.expected_trigger == "resource_unavailable":
        workers.register(
            "resource_planning",
            ResourcePlanningWorker(
                retrieval, ScenarioResourceGenerator(), max_queries=case.max_queries
            ),
        )
        planner = ResourcePlanner()
    elif case.expected_trigger == "artifact_conflict":
        workers.register(
            "impact_safety",
            ImpactSafetyWorker(
                retrieval, ScenarioImpactGenerator(), max_queries=case.max_queries
            ),
        )
        workers.register(
            "diagnosis",
            DiagnosisWorker(
                retrieval,
                ScenarioDiagnosisGenerator(
                    {"conflict": "诊断结论与影响评估结论相悖。"}
                ),
                max_queries=case.max_queries,
            ),
        )
        planner = ConflictPlanner()
    else:
        workers.register(
            "diagnosis",
            DiagnosisWorker(
                retrieval,
                ScenarioDiagnosisGenerator(
                    {"hypothesis_revised": "新日志推翻了初始根因假设。"}
                ),
                max_queries=case.max_queries,
            ),
        )
        planner = DiagnosisPlanner()
    runtime = PlanningRuntime(
        planner,
        PlanController(store, PlanValidator()),
        workers,
        store,
        RuleBasedReplanner(),
        RuleBasedReplanDetector(),
    )
    incident = IncidentContext(
        incident_id=case.case_id,
        tenant_id="tenant-eval",
        thread_id=f"thread-{case.case_id}",
        goal=case.goal,
        trace_id=f"eval-{case.case_id}",
    )
    result = await runtime.run(incident)
    return _evaluate_result(case, result, provider)


# 汇总单个用例的断言：触发类型、原子版本提交、只读与预算守恒。
def _evaluate_result(case, result, provider) -> dict:
    # 原始制品按触发器对应的 Worker 角色挑选，避免误取影响评估等其他角色制品。
    original_role = (
        "resource_planning"
        if case.expected_trigger == "resource_unavailable"
        else "diagnosis"
    )
    original = next(
        (
            item
            for item in result.artifacts
            if item.worker_id == original_role
            and not item.task_id.endswith("-revised")
        ),
        None,
    )
    revised = next(
        (item for item in result.artifacts if item.task_id.endswith("-revised")), None
    )
    expected_trigger_detected = _marker_matches(case.expected_trigger, original)
    revised_clean = _revised_clean(case.expected_trigger, revised)
    version_committed = result.plan_version == case.expected_plan_version
    replan_exact = result.replan_count == 1
    read_only_preserved = bool(provider.contexts) and all(
        context.chain == "investigation" and context.permissions == {"tool:read"}
        for context in provider.contexts
    )
    query_budget_respected = len(provider.contexts) <= (
        case.max_queries * 2
    )
    passed = (
        result.status == "completed"
        and expected_trigger_detected
        and revised_clean
        and version_committed
        and replan_exact
        and read_only_preserved
        and query_budget_respected
    )
    return {
        "case_id": case.case_id,
        "status": result.status,
        "expected_trigger": case.expected_trigger,
        "replan_count": result.replan_count,
        "plan_version": result.plan_version,
        "expected_trigger_detected": expected_trigger_detected,
        "revised_clean": revised_clean,
        "version_committed": version_committed,
        "read_only_preserved": read_only_preserved,
        "query_budget_respected": query_budget_respected,
        "retrieval_calls": len(provider.contexts),
        "passed": passed,
    }


# 判断原始制品是否携带期望触发器标记。
def _marker_matches(trigger: str, artifact) -> bool:
    if artifact is None:
        return False
    if trigger == "resource_unavailable":
        resource_planning = artifact.payload.get("resource_planning") or {}
        return resource_planning.get("primary_available") is False
    diagnosis = artifact.payload.get("diagnosis") or {}
    if trigger == "artifact_conflict":
        return bool(diagnosis.get("conflict"))
    return bool(diagnosis.get("hypothesis_revised"))


# 判断重规划后的修订制品是否已清除触发标记。
def _revised_clean(trigger: str, artifact) -> bool:
    if artifact is None:
        return False
    if trigger == "resource_unavailable":
        resource_planning = artifact.payload.get("resource_planning") or {}
        return resource_planning.get("primary_available") is True
    diagnosis = artifact.payload.get("diagnosis") or {}
    return not diagnosis.get("conflict") and not diagnosis.get("hypothesis_revised")


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


# 使用通用报告写入器保存 Replan 评测结果。
def write_replanning_report(report: dict, path: Path) -> None:
    write_json_report(report, path)
