from flowfix_agent.knowledge.models import SourceType
from flowfix_agent.memory.task_artifact import SQLiteTaskArtifactStore
from flowfix_agent.planning.controller import PlanController
from flowfix_agent.planning.models import IncidentContext, PlanDraft, TaskSpec
from flowfix_agent.planning.registry import WorkerRegistry
from flowfix_agent.planning.runtime import PlanningRuntime
from flowfix_agent.planning.validation import PlanValidator
from flowfix_agent.planning.workers.resource_planning import (
    ResourceCandidate,
    ResourceKind,
    ResourcePlanningResult,
    ResourcePlanningWorker,
)
from flowfix_agent.retrieval.models import Evidence, EvidenceBundle, RetrievalMode


# 固定 Planner：产出单条 resource_planning 任务。
class FakePlanner:
    async def plan(self, incident):
        return PlanDraft(
            plan_id="plan-resource",
            tasks=[
                TaskSpec(
                    task_id="resource",
                    description=incident.goal,
                    required_role="resource_planning",
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
                title="备件台账",
                section_path="",
                content="DEV-1 使用 2.5 寸 SATA 企业级硬盘，仓库库存充足，值班工程师可安排换盘。",
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


# 确定性生成器：引用首个证据编号并产出合法资源规划结果。
class FakeGenerator:
    model = "fake"

    async def generate(self, incident, task, evidence):
        first = evidence[0].citation_id
        return ResourcePlanningResult(
            primary_available=True,
            confidence=0.8,
            candidates=[
                ResourceCandidate(
                    candidate_id="c1",
                    kind=ResourceKind.SPARE_PART,
                    name="2.5 寸 SATA 硬盘",
                    description="仓库库存充足，可即时领取。",
                    available=True,
                    supporting_evidence=[first],
                )
            ],
            conflicts=[],
            alternatives=[],
            missing_info=["备件到货时间"],
        )


# 验证五节点运行时执行真实 ResourcePlanning Worker 并持久化只生成 proposal 的 Artifact。
async def test_planning_runtime_runs_real_resource_planning_worker(tmp_path):
    store = SQLiteTaskArtifactStore(tmp_path / "planning-resource.db")
    retrieval = FakeRetrieval()
    worker = ResourcePlanningWorker(retrieval, FakeGenerator(), max_queries=3)
    registry = WorkerRegistry()
    registry.register("resource_planning", worker)
    runtime = PlanningRuntime(
        FakePlanner(), PlanController(store, PlanValidator()), registry, store
    )

    result = await runtime.run(
        IncidentContext(
            incident_id="incident-1",
            tenant_id="tenant-1",
            thread_id="thread-1",
            goal="规划更换 DEV-1 故障硬盘所需的人员、备件与维护窗口",
            trace_id="trace-1",
        )
    )

    assert result.status == "completed"
    assert len(result.artifacts) == 1
    artifact = result.artifacts[0]
    assert artifact.worker_id == "resource_planning"
    assert 0 <= artifact.confidence <= 1
    assert artifact.evidence_refs == ["chunk-1"]
    assert retrieval.calls <= 3
    persisted = store.list_plan("tenant-1", "thread-1", "plan-resource")
    artifact_records = [record for record in persisted if record.kind == "artifact"]
    assert len(artifact_records) == 1
    planning = artifact_records[0].payload["payload"]["resource_planning"]
    assert planning["primary_available"] is True
    assert len(planning["candidates"]) == 1
    # proposal 守恒：候选 available 标记存在，但没有任何写/预留能力进入 Artifact 载荷。
    assert "assign" not in json_payload_keys(artifact_records[0].payload["payload"])
    assert artifact_records[0].payload["payload"]["evidence"][0]["citation_id"] == 1


# 返回载荷 JSON 的所有嵌套键，用于断言不含任何写操作字段。
def json_payload_keys(payload: dict) -> set[str]:
    keys = set(payload.keys())
    for value in payload.values():
        if isinstance(value, dict):
            keys |= json_payload_keys(value)
    return keys
