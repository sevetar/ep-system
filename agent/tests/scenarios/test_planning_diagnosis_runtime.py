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
from flowfix_agent.retrieval.models import Evidence, EvidenceBundle, RetrievalMode


# 固定 Planner：产出单条 diagnosis 任务。
class FakePlanner:
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
                content="设备停机常见根因。",
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


# 确定性生成器：引用首个证据编号并产出合法假设。
class FakeGenerator:
    model = "fake"

    async def generate(self, incident, task, evidence):
        return DiagnosisResult(
            conclusion="根因为组件 A 故障。",
            confidence=0.8,
            hypotheses=[
                DiagnosisHypothesis(
                    hypothesis_id="h1",
                    title="组件 A 故障",
                    summary="证据支持。",
                    supporting_evidence=[evidence[0].citation_id],
                    opposing_evidence=[],
                    confidence=0.8,
                    missing_info=["备件数据"],
                )
            ],
            missing_info=["备件数据"],
        )


# 验证五节点运行时执行真实 Diagnosis Worker 并持久化带来源的 Artifact。
async def test_planning_runtime_runs_real_diagnosis_worker(tmp_path):
    store = SQLiteTaskArtifactStore(tmp_path / "planning-diag.db")
    retrieval = FakeRetrieval()
    worker = DiagnosisWorker(retrieval, FakeGenerator(), max_queries=3)
    registry = WorkerRegistry()
    registry.register("diagnosis", worker)
    runtime = PlanningRuntime(
        FakePlanner(), PlanController(store, PlanValidator()), registry, store
    )

    result = await runtime.run(
        IncidentContext(
            incident_id="incident-1",
            tenant_id="tenant-1",
            thread_id="thread-1",
            goal="排查设备 DEV-1 停机",
            trace_id="trace-1",
        )
    )

    assert result.status == "completed"
    assert len(result.artifacts) == 1
    artifact = result.artifacts[0]
    assert artifact.worker_id == "diagnosis"
    assert 0 <= artifact.confidence <= 1
    assert artifact.evidence_refs == ["chunk-1"]
    assert retrieval.calls <= 3
    persisted = store.list_plan("tenant-1", "thread-1", "plan-diag")
    artifact_records = [record for record in persisted if record.kind == "artifact"]
    assert len(artifact_records) == 1
    diagnosis = artifact_records[0].payload["payload"]["diagnosis"]
    assert diagnosis["conclusion"].find("组件 A") != -1
