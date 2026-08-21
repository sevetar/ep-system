from flowfix_agent.memory.task_artifact import SQLiteTaskArtifactStore
from flowfix_agent.planning.completion import CompletionGate
from flowfix_agent.planning.controller import PlanController
from flowfix_agent.planning.models import (
    Artifact,
    IncidentContext,
    PlanDraft,
    PlanningHumanInput,
    TaskSpec,
)
from flowfix_agent.planning.registry import WorkerRegistry
from flowfix_agent.planning.runtime import PlanningRuntime
from flowfix_agent.planning.validation import PlanValidator


# 诊断 Worker：按标志产出干净或拒答制品。
class DiagnosisWorker:
    worker_id = "diagnosis"

    def __init__(self, refuse: bool = False) -> None:
        self.refuse = refuse

    async def execute(self, incident, task, dependency_artifacts, *, plan_version=1):
        if self.refuse:
            diagnosis = {
                "conclusion": "拒答",
                "confidence": 0,
                "hypotheses": [],
                "missing_info": ["缺少故障日志证据"],
            }
        else:
            diagnosis = {
                "conclusion": "电源模块故障",
                "confidence": 0.8,
                "hypotheses": [{"hypothesis_id": "h1", "title": "电源模块老化"}],
                "missing_info": [],
            }
        return Artifact(
            artifact_id=f"artifact-{task.task_id}",
            task_id=task.task_id,
            plan_version=plan_version,
            worker_id=self.worker_id,
            payload={"diagnosis": diagnosis, "evidence_count": 1},
            evidence_refs=["chunk-1"],
            confidence=diagnosis["confidence"],
        )


# 影响评估 Worker：高风险时必须附安全约束，否则门禁判定未承认风险。
class ImpactWorker:
    worker_id = "impact_safety"

    def __init__(self, with_safety: bool = True) -> None:
        self.with_safety = with_safety

    async def execute(self, incident, task, dependency_artifacts, *, plan_version=1):
        impact = {
            "overall_risk_level": "critical",
            "impact_scopes": [{"scope_id": "s1", "target": "下游产线"}],
        }
        if self.with_safety:
            impact["safety_constraints"] = [
                {"constraint_id": "c1", "action": "禁止带电作业"}
            ]
        return Artifact(
            artifact_id=f"artifact-{task.task_id}",
            task_id=task.task_id,
            plan_version=plan_version,
            worker_id=self.worker_id,
            payload={"impact_safety": impact, "evidence_count": 1},
            evidence_refs=["chunk-1"],
            confidence=0.9,
        )


# 固定 Planner：诊断任务依赖影响任务，模拟完整调查链。
class DiagnosisImpactPlanner:
    async def plan(self, incident):
        return PlanDraft(
            plan_id="plan-complete",
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


# 固定 Planner：单个诊断任务。
class SingleDiagnosisPlanner:
    async def plan(self, incident):
        return PlanDraft(
            plan_id="plan-diag",
            tasks=[
                TaskSpec(
                    task_id="diagnose",
                    description=incident.goal,
                    required_role="diagnosis",
                    allowed_capabilities={"knowledge.search"},
                )
            ],
        )


def _incident(incident_id: str, goal: str, **overrides) -> IncidentContext:
    values = {
        "incident_id": incident_id,
        "tenant_id": "tenant-1",
        "thread_id": "thread-1",
        "goal": goal,
        "trace_id": "trace-1",
        "success_criteria": ["定位根因", "评估影响范围"],
    }
    values.update(overrides)
    return IncidentContext(**values)


def _runtime(
    planner, registry, tmp_path, db: str, gate: CompletionGate | None
) -> PlanningRuntime:
    store = SQLiteTaskArtifactStore(tmp_path / db)
    return PlanningRuntime(
        planner,
        PlanController(store, PlanValidator()),
        registry,
        store,
        completion_gate=gate,
    )


# 验证完成门禁批准时正常完成：全部任务完成、无拒答、高风险已承认。
async def test_gate_approves_completion(tmp_path):
    registry = WorkerRegistry()
    registry.register("diagnosis", DiagnosisWorker())
    registry.register("impact_safety", ImpactWorker())
    runtime = _runtime(
        DiagnosisImpactPlanner(),
        registry,
        tmp_path,
        "completion-ok.db",
        CompletionGate(),
    )

    result = await runtime.run(_incident("i1", "定位设备停机根因并评估影响"))

    assert result.status == "completed"
    assert result.replan_count == 0
    assert {item.worker_id for item in result.artifacts} == {"diagnosis", "impact_safety"}


# 验证拒答制品阻断完成：门禁拒绝 → 转人工补充证据。
async def test_gate_blocks_refusal_and_awaits_human(tmp_path):
    registry = WorkerRegistry()
    registry.register("diagnosis", DiagnosisWorker(refuse=True))
    runtime = _runtime(
        SingleDiagnosisPlanner(),
        registry,
        tmp_path,
        "completion-refusal.db",
        CompletionGate(),
    )

    result = await runtime.run(_incident("i2", "定位故障根因"))

    assert result.status == "awaiting_human"
    assert "拒答制品" in result.report
    assert "需要人工补充信息" in result.report
    assert result.proposal is None


async def test_planning_human_input_resumes_original_checkpoint(tmp_path):
    worker = DiagnosisWorker(refuse=True)
    registry = WorkerRegistry()
    registry.register("diagnosis", worker)
    runtime = _runtime(
        SingleDiagnosisPlanner(),
        registry,
        tmp_path,
        "completion-resume.db",
        CompletionGate(),
    )
    incident = _incident(
        "i-resume", "定位故障根因", success_criteria=["定位根因"]
    )

    paused = await runtime.run(incident)
    worker.refuse = False
    completed = await runtime.resume(
        paused.thread_id,
        PlanningHumanInput(action="retry", information="已补充电源模块检测日志"),
        tenant_id="tenant-1",
    )

    assert paused.interrupted is True
    assert completed.status == "completed"
    assert completed.thread_id == paused.thread_id


# 验证高风险未被安全约束承认时阻断完成：门禁拒绝 → 转人工。
async def test_gate_blocks_unacknowledged_high_risk(tmp_path):
    registry = WorkerRegistry()
    registry.register("diagnosis", DiagnosisWorker())
    registry.register("impact_safety", ImpactWorker(with_safety=False))
    runtime = _runtime(
        DiagnosisImpactPlanner(),
        registry,
        tmp_path,
        "completion-risk.db",
        CompletionGate(),
    )

    result = await runtime.run(_incident("i3", "定位设备停机根因并评估影响"))

    assert result.status == "awaiting_human"
    assert "高风险" in result.report


# 验证完成时按 dispatch_target 产出只读 DispatchProposal。
async def test_gate_produces_dispatch_proposal(tmp_path):
    registry = WorkerRegistry()
    registry.register("diagnosis", DiagnosisWorker())
    registry.register("impact_safety", ImpactWorker())
    runtime = _runtime(
        DiagnosisImpactPlanner(),
        registry,
        tmp_path,
        "completion-proposal.db",
        CompletionGate(),
    )

    result = await runtime.run(
        _incident("i4", "定位设备停机根因并评估影响", dispatch_target="WO-42")
    )

    assert result.status == "completed"
    assert result.proposal is not None
    assert result.proposal.work_order_id == "WO-42"
    assert result.proposal.requires_approval is True
    assert result.proposal.evidence_refs == ["chunk-1"]
    assert result.proposal.risk_level == "critical"


# 验证未注入门禁时向后兼容：即使拒答制品也直接完成，门禁是可选策略。
async def test_without_gate_completes_backward_compatible(tmp_path):
    registry = WorkerRegistry()
    registry.register("diagnosis", DiagnosisWorker(refuse=True))
    runtime = _runtime(
        SingleDiagnosisPlanner(),
        registry,
        tmp_path,
        "completion-nogate.db",
        None,
    )

    result = await runtime.run(_incident("i5", "定位故障根因"))

    assert result.status == "completed"
    assert result.proposal is None
