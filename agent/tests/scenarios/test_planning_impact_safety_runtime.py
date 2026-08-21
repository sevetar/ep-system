from flowfix_agent.knowledge.models import SourceType
from flowfix_agent.memory.task_artifact import SQLiteTaskArtifactStore
from flowfix_agent.planning.controller import PlanController
from flowfix_agent.planning.models import IncidentContext, PlanDraft, TaskSpec
from flowfix_agent.planning.registry import WorkerRegistry
from flowfix_agent.planning.runtime import PlanningRuntime
from flowfix_agent.planning.validation import PlanValidator
from flowfix_agent.planning.workers.impact_safety import (
    ImpactSafetyResult,
    ImpactSafetyWorker,
    ImpactScope,
    MandatoryCheck,
    RiskItem,
    RiskLevel,
    SafetyConstraint,
)
from flowfix_agent.retrieval.models import Evidence, EvidenceBundle, RetrievalMode


# 固定 Planner：产出单条 impact_safety 任务。
class FakePlanner:
    async def plan(self, incident):
        return PlanDraft(
            plan_id="plan-impact",
            tasks=[
                TaskSpec(
                    task_id="impact",
                    description=incident.goal,
                    required_role="impact_safety",
                    allowed_capabilities={"knowledge.search"},
                )
            ],
        )


# 只读检索桩：任何查询都返回固定证据。
class FakeRetrieval:
    def __init__(self) -> None:
        self.calls = 0

    async def retrieve(self, query, scope, options, trace_id=None, *, chain, role):
        self.calls += 1
        evidence = [
            Evidence(
                citation_id=1,
                chunk_id="chunk-1",
                source_id="chunk-1",
                source_type=SourceType.PLATFORM_DOC,
                source_version="1.0.0",
                title="手册",
                section_path="",
                content="设备停机将导致下游产线停摆，涉及带电检修必须先隔离电源。",
                score=0.9,
                estimated_tokens=10,
            )
        ]
        return EvidenceBundle(
            trace_id=trace_id or "t",
            original_query=query,
            retrieval_query=query,
            mode=RetrievalMode.HYBRID,
            scope=scope,
            candidates=[],
            selected_evidence=evidence,
            budget_used=0,
            sufficient=True,
            latency_ms=0.0,
        )


# 确定性生成器：引用首个证据编号并产出合法评估结果。
class FakeGenerator:
    model = "fake"

    async def generate(self, incident, task, evidence):
        first = evidence[0].citation_id
        return ImpactSafetyResult(
            overall_risk_level=RiskLevel.CRITICAL,
            confidence=0.8,
            impact_scopes=[
                ImpactScope(
                    scope_id="s1",
                    target="下游产线",
                    description="设备停机会导致下游产线停摆。",
                    supporting_evidence=[first],
                )
            ],
            risks=[
                RiskItem(
                    risk_id="r1",
                    title="连锁停机",
                    description="故障可能引发连锁停机。",
                    severity=RiskLevel.CRITICAL,
                    supporting_evidence=[first],
                )
            ],
            safety_constraints=[
                SafetyConstraint(
                    constraint_id="c1",
                    action="禁止带电检修。",
                    rationale="防止人身伤害。",
                    supporting_evidence=[first],
                )
            ],
            mandatory_checks=[
                MandatoryCheck(
                    check_id="m1",
                    item="处置前确认电源已隔离。",
                    supporting_evidence=[first],
                )
            ],
            missing_info=["现场巡检数据"],
        )


# 验证五节点运行时执行真实 ImpactSafety Worker 并持久化带来源、守恒的 Artifact。
async def test_planning_runtime_runs_real_impact_safety_worker(tmp_path):
    store = SQLiteTaskArtifactStore(tmp_path / "planning-impact.db")
    retrieval = FakeRetrieval()
    worker = ImpactSafetyWorker(retrieval, FakeGenerator(), max_queries=3)
    registry = WorkerRegistry()
    registry.register("impact_safety", worker)
    runtime = PlanningRuntime(
        FakePlanner(), PlanController(store, PlanValidator()), registry, store
    )

    result = await runtime.run(
        IncidentContext(
            incident_id="incident-1",
            tenant_id="tenant-1",
            thread_id="thread-1",
            goal="评估设备停机的影响范围与安全约束",
            trace_id="trace-1",
        )
    )

    assert result.status == "completed"
    assert len(result.artifacts) == 1
    artifact = result.artifacts[0]
    assert artifact.worker_id == "impact_safety"
    assert 0 <= artifact.confidence <= 1
    assert artifact.evidence_refs == ["chunk-1"]
    assert retrieval.calls <= 3
    persisted = store.list_plan("tenant-1", "thread-1", "plan-impact")
    artifact_records = [record for record in persisted if record.kind == "artifact"]
    assert len(artifact_records) == 1
    impact = artifact_records[0].payload["payload"]["impact_safety"]
    assert impact["overall_risk_level"] == "critical"
    # 整体风险等级不得低于任一已识别风险的最高等级。
    assert len(impact["risks"]) == 1
    assert impact["risks"][0]["severity"] == "critical"
