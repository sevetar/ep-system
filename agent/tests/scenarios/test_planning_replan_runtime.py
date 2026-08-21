from flowfix_agent.knowledge.models import SourceType
from flowfix_agent.memory.task_artifact import SQLiteTaskArtifactStore
from flowfix_agent.planning.controller import PlanController
from flowfix_agent.planning.models import (
    Artifact,
    IncidentContext,
    PlanDraft,
    TaskSpec,
)
from flowfix_agent.planning.registry import WorkerRegistry
from flowfix_agent.planning.replanning import RuleBasedReplanDetector, RuleBasedReplanner
from flowfix_agent.planning.runtime import PlanningRuntime
from flowfix_agent.planning.validation import PlanValidator
from flowfix_agent.retrieval.models import Evidence, EvidenceBundle, RetrievalMode


# 只读检索桩：任何查询都返回固定证据。
class FakeRetrieval:
    async def retrieve(self, query, scope, options, trace_id=None, *, chain, role):
        evidence = [
            Evidence(
                citation_id=1,
                chunk_id="chunk-1",
                source_id="chunk-1",
                source_type=SourceType.PLATFORM_DOC,
                source_version="1.0.0",
                title="手册",
                section_path="",
                content="设备故障相关手册内容。",
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


# 诊断 Worker：首次调用携带指定标记，重规划后的「-revised」任务输出干净结果。
class FlaggedDiagnosisWorker:
    worker_id = "diagnosis"

    def __init__(self, marker: dict) -> None:
        self.marker = marker
        self.calls = 0

    async def execute(self, incident, task, dependency_artifacts, *, plan_version=1):
        self.calls += 1
        revised = task.task_id.endswith("-revised")
        diagnosis = {
            "conclusion": "根因假设",
            "confidence": 0.8,
            "hypotheses": [],
            "missing_info": [],
            "hypothesis_revised": None,
            "conflict": None,
        }
        if not revised:
            diagnosis.update(self.marker)
        return Artifact(
            artifact_id=f"artifact-{task.task_id}",
            task_id=task.task_id,
            plan_version=plan_version,
            worker_id=self.worker_id,
            payload={"diagnosis": diagnosis, "evidence_count": 1},
            confidence=0.8,
        )


# 资源规划 Worker：首次返回主资源不可用，重规划后的「-revised」任务返回可用。
class UnavailableResourceWorker:
    worker_id = "resource_planning"

    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, incident, task, dependency_artifacts, *, plan_version=1):
        self.calls += 1
        available = task.task_id.endswith("-revised")
        return Artifact(
            artifact_id=f"artifact-{task.task_id}",
            task_id=task.task_id,
            plan_version=plan_version,
            worker_id=self.worker_id,
            payload={
                "resource_planning": {
                    "primary_available": available,
                    "confidence": 0.8,
                    "candidates": [],
                    "conflicts": [] if available else ["cf1"],
                    "alternatives": ["a1"] if not available else [],
                    "missing_info": [] if available else ["备件到货时间"],
                },
                "evidence_count": 1,
            },
            confidence=0.8,
        )


# 影响评估 Worker：产出固定高风险结论，供诊断冲突场景作依赖输入。
class ImpactWorker:
    worker_id = "impact_safety"

    async def execute(self, incident, task, dependency_artifacts, *, plan_version=1):
        return Artifact(
            artifact_id=f"artifact-{task.task_id}",
            task_id=task.task_id,
            plan_version=plan_version,
            worker_id=self.worker_id,
            payload={"impact_safety": {"overall_risk_level": "critical"}},
            confidence=0.9,
        )


# 固定 Planner：诊断任务依赖影响任务（先评估影响，再诊断根因并核对一致性）。
class ConflictPlanner:
    async def plan(self, incident):
        return PlanDraft(
            plan_id="plan-conflict",
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


# 固定 Planner：单个资源规划任务。
class ResourcePlanner:
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


def _incident(incident_id: str, goal: str) -> IncidentContext:
    return IncidentContext(
        incident_id=incident_id,
        tenant_id="tenant-1",
        thread_id="thread-1",
        goal=goal,
        trace_id="trace-1",
    )


def _runtime(planner, registry, tmp_path, db: str) -> PlanningRuntime:
    store = SQLiteTaskArtifactStore(tmp_path / db)
    return PlanningRuntime(
        planner,
        PlanController(store, PlanValidator()),
        registry,
        store,
        RuleBasedReplanner(),
        RuleBasedReplanDetector(),
    )


# 验证新证据推翻初始假设：检测 new_evidence → Replan → 修订任务完成 → plan 版本递增。
async def test_runtime_replans_on_new_evidence(tmp_path):
    worker = FlaggedDiagnosisWorker(
        {"hypothesis_revised": "新日志显示为磁盘故障而非电源故障"}
    )
    registry = WorkerRegistry()
    registry.register("diagnosis", worker)
    runtime = _runtime(SingleDiagnosisPlanner(), registry, tmp_path, "replan-new.db")

    result = await runtime.run(_incident("i1", "定位故障根因"))

    assert result.status == "completed"
    assert result.replan_count == 1
    assert result.plan_version == 2
    assert [item.task_id for item in result.artifacts] == ["diagnose", "diagnose-revised"]
    assert worker.calls == 2
    # 修订制品必须归属 Replan 后的新版本，否则 RuleBasedReplanDetector 的版本门控会漏判。
    assert result.artifacts[1].plan_version == 2


# 验证诊断与影响结论冲突：检测 artifact_conflict → Replan → 修订诊断完成。
async def test_runtime_replans_on_artifact_conflict(tmp_path):
    diagnosis = FlaggedDiagnosisWorker(
        {"conflict": "诊断结论为电源故障，与影响评估的存储故障结论相悖"}
    )
    registry = WorkerRegistry()
    registry.register("diagnosis", diagnosis)
    registry.register("impact_safety", ImpactWorker())
    runtime = _runtime(ConflictPlanner(), registry, tmp_path, "replan-conflict.db")

    result = await runtime.run(_incident("i2", "定位设备停机根因并评估影响"))

    assert result.status == "completed"
    assert result.replan_count == 1
    assert result.plan_version == 2
    # 首次批次：impact + diagnose；重规划后仅重新执行 diagnose-revised。
    assert [item.task_id for item in result.artifacts] == [
        "impact",
        "diagnose",
        "diagnose-revised",
    ]
    assert diagnosis.calls == 2
    # 修订后的诊断制品归属 Replan 后的版本，避免被版本门控过滤。
    assert result.artifacts[2].plan_version == 2


# 验证关键备件不可用：检测 resource_unavailable → Replan → 修订资源任务完成。
async def test_runtime_replans_on_resource_unavailable(tmp_path):
    worker = UnavailableResourceWorker()
    registry = WorkerRegistry()
    registry.register("resource_planning", worker)
    runtime = _runtime(ResourcePlanner(), registry, tmp_path, "replan-resource.db")

    result = await runtime.run(_incident("i3", "规划关键备件供应方案"))

    assert result.status == "completed"
    assert result.replan_count == 1
    assert result.plan_version == 2
    assert [item.task_id for item in result.artifacts] == ["resource", "resource-revised"]
    assert worker.calls == 2
    # 修订后的制品归属 Replan 后的新版本。
    assert result.artifacts[1].plan_version == 2
    # 修订后的任务产出主资源可用结论。
    revised = next(item for item in result.artifacts if item.task_id == "resource-revised")
    assert revised.payload["resource_planning"]["primary_available"] is True


# 验证无触发信号时正常运行：诊断直接完成，不重规划。
async def test_runtime_completes_without_replan(tmp_path):
    worker = FlaggedDiagnosisWorker({})
    registry = WorkerRegistry()
    registry.register("diagnosis", worker)
    runtime = _runtime(SingleDiagnosisPlanner(), registry, tmp_path, "replan-none.db")

    result = await runtime.run(_incident("i4", "定位故障根因"))

    assert result.status == "completed"
    assert result.replan_count == 0
    assert result.plan_version == 1
    assert worker.calls == 1
