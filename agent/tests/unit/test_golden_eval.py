import pytest

from flowfix_agent.evaluation.golden import (
    FaultyOnceDiagnosisWorker,
    FullInvestigationPlanner,
    GoldenCase,
    _assemble_scenario,
    _build_table,
    _CleanResourceGenerator,
    _refusal_present,
    _unacknowledged_risk,
)
from flowfix_agent.evaluation.impact_safety import CannedEvidenceItem
from flowfix_agent.knowledge.models import SourceType
from flowfix_agent.planning.models import Artifact, IncidentContext
from flowfix_agent.planning.registry import WorkerRegistry
from flowfix_agent.planning.workers.diagnosis import DiagnosisWorker
from flowfix_agent.planning.workers.impact_safety import RiskLevel
from flowfix_agent.planning.workers.resource_planning import ResourcePlanningWorker


# 将 CannedEvidenceItem 证据表转换为检索 Evidence：字段、来源与分数固定。
def test_build_table_converts_evidence_items():
    raw = {
        "备件": [
            CannedEvidenceItem(chunk_id="c1", title="备件台账", content="备件供应说明。")
        ]
    }

    table = _build_table(raw)
    item = table["备件"][0]

    assert item.chunk_id == "c1"
    assert item.source_id == "c1"
    assert item.source_type == SourceType.PLATFORM_DOC
    assert item.source_version == "1.0.0"
    assert item.title == "备件台账"
    assert item.score == 0.9
    assert item.citation_id == 1
    assert item.estimated_tokens == len("备件供应说明。")


# FaultyOnceDiagnosisWorker 首次调用注入故障，之后委托内部 Worker 产出制品。
async def test_faulty_once_worker_raises_then_delegates():
    class RecordingInner:
        worker_id = "diagnosis"

        async def execute(self, incident, task, dependency_artifacts, *, plan_version=1):
            return "ok"

    worker = FaultyOnceDiagnosisWorker(RecordingInner())

    with pytest.raises(RuntimeError):
        await worker.execute(None, None, [])
    assert await worker.execute(None, None, []) == "ok"
    assert worker.calls == 2


# 干净资源生成器始终产出主资源可用、有替代方案且无冲突的结果。
async def test_clean_resource_generator_always_available():
    gen = _CleanResourceGenerator()
    incident = IncidentContext(
        incident_id="i1", tenant_id="t", thread_id="th", goal="规划备件", trace_id="tr"
    )
    evidence = _build_table({"备件": [CannedEvidenceItem(chunk_id="c1", content="说明")]})[
        "备件"
    ]

    result = await gen.generate(incident, None, evidence)

    assert result.primary_available is True
    assert result.conflicts == []
    assert result.alternatives
    assert result.candidates[0].available is True
    assert result.candidates[0].supporting_evidence == [1]


# FullInvestigationPlanner 生成影响→诊断→资源的依赖链，覆盖三类成功标准。
async def test_full_investigation_planner_structure():
    incident = IncidentContext(
        incident_id="i1", tenant_id="t", thread_id="th", goal="目标", trace_id="tr"
    )

    draft = await FullInvestigationPlanner().plan(incident)
    by_id = {task.task_id: task for task in draft.tasks}

    assert list(by_id) == ["impact", "diagnose", "resource"]
    assert by_id["impact"].required_role == "impact_safety"
    assert by_id["diagnose"].required_role == "diagnosis"
    assert by_id["diagnose"].dependencies == ["impact"]
    assert by_id["resource"].required_role == "resource_planning"
    assert by_id["resource"].dependencies == ["diagnose"]
    for task in draft.tasks:
        assert task.allowed_capabilities == {"knowledge.search"}


def _artifact(task_id: str, worker_id: str, payload: dict) -> Artifact:
    return Artifact(
        artifact_id=f"artifact-{task_id}",
        task_id=task_id,
        plan_version=1,
        worker_id=worker_id,
        payload=payload,
        confidence=0.5,
    )


# 拒答制品（无假设且置信度为 0）被识别，干净诊断不被误判。
def test_refusal_present_detects_refusal():
    refusal = _artifact(
        "diag", "diagnosis", {"diagnosis": {"hypotheses": [], "confidence": 0}}
    )
    assert _refusal_present([refusal]) is True

    clean = _artifact(
        "diag",
        "diagnosis",
        {"diagnosis": {"hypotheses": [{"hypothesis_id": "h1"}], "confidence": 0.8}},
    )
    assert _refusal_present([clean]) is False
    assert _refusal_present([]) is False


# 高风险未附安全约束/必选校验才算未承认；中风险或带约束不算。
def test_unacknowledged_risk():
    critical_no_safety = _artifact(
        "impact", "impact_safety", {"impact_safety": {"overall_risk_level": "critical"}}
    )
    assert _unacknowledged_risk([critical_no_safety]) is True

    with_safety = _artifact(
        "impact",
        "impact_safety",
        {
            "impact_safety": {
                "overall_risk_level": "critical",
                "safety_constraints": ["c1"],
            }
        },
    )
    assert _unacknowledged_risk([with_safety]) is False

    medium = _artifact(
        "impact", "impact_safety", {"impact_safety": {"overall_risk_level": "medium"}}
    )
    assert _unacknowledged_risk([medium]) is False

    non_impact = _artifact(
        "diag", "diagnosis", {"diagnosis": {"overall_risk_level": "critical"}}
    )
    assert _unacknowledged_risk([non_impact]) is False


# _assemble_scenario 按场景注册正确角色集合，全部只读 Worker。
def test_assemble_scenario_registers_expected_roles():
    cases = {
        "basic": {"diagnosis", "impact_safety"},
        "with-resource": {"diagnosis", "impact_safety", "resource_planning"},
        "replan-new-evidence": {"diagnosis"},
        "replan-conflict": {"impact_safety", "diagnosis"},
        "replan-resource": {"resource_planning"},
        "refusal-blocked": {"diagnosis", "impact_safety"},
        "high-risk-blocked": {"diagnosis", "impact_safety"},
        "uncovered-criterion": {"diagnosis", "impact_safety"},
        "recovery-failed-task": {"diagnosis"},
    }
    for scenario, roles in cases.items():
        case = GoldenCase(
            case_id=f"case-{scenario}",
            goal="目标",
            scenario=scenario,
            expected_status="completed",
        )
        workers = WorkerRegistry()
        _assemble_scenario(case, workers, None)
        assert set(workers._workers) == roles, scenario


# 高风险阻断场景必须注册不带安全约束的 critical 影响 Worker。
def test_high_risk_scenario_uses_unconstrained_critical_generator():
    case = GoldenCase(
        case_id="case-hr",
        goal="评估高风险影响",
        scenario="high-risk-blocked",
        expected_status="awaiting_human",
    )
    workers = WorkerRegistry()
    _assemble_scenario(case, workers, None)

    impact = workers.resolve("impact_safety")
    assert impact.generator.risk_level is RiskLevel.CRITICAL
    assert impact.generator.with_safety is False


# 冲突场景的影响评估必须用干净中风险制品，避免完成门禁被高风险阻断。
def test_conflict_scenario_uses_gate_clean_impact_generator():
    case = GoldenCase(
        case_id="case-cf",
        goal="定位根因并评估影响",
        scenario="replan-conflict",
        expected_status="completed",
    )
    workers = WorkerRegistry()
    _assemble_scenario(case, workers, None)

    impact = workers.resolve("impact_safety")
    assert impact.generator.risk_level is RiskLevel.MEDIUM
    assert impact.generator.with_safety is True


# 故障恢复场景注册首次抛错的诊断 Worker，恢复后仍是干净诊断。
def test_recovery_scenario_wraps_diagnosis_worker():
    case = GoldenCase(
        case_id="case-rc",
        goal="定位故障根因",
        scenario="recovery-failed-task",
        expected_status="completed",
    )
    workers = WorkerRegistry()
    _assemble_scenario(case, workers, None)

    diag = workers.resolve("diagnosis")
    assert isinstance(diag, FaultyOnceDiagnosisWorker)
    assert isinstance(diag.inner, DiagnosisWorker)


# with-resource 场景注册三个干净 Worker 并返回全链路 Planner。
def test_with_resource_scenario_registers_three_workers():
    case = GoldenCase(
        case_id="case-wr",
        goal="定位、评估并规划备件",
        scenario="with-resource",
        expected_status="completed",
    )
    workers = WorkerRegistry()
    _assemble_scenario(case, workers, None)

    assert isinstance(workers.resolve("diagnosis"), DiagnosisWorker)
    assert isinstance(workers.resolve("impact_safety"), object)
    assert isinstance(workers.resolve("resource_planning"), ResourcePlanningWorker)
