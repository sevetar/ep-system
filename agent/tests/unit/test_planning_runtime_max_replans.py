from flowfix_agent.memory.task_artifact import SQLiteTaskArtifactStore
from flowfix_agent.planning.controller import PlanController
from flowfix_agent.planning.models import (
    Artifact,
    IncidentContext,
    PlanDraft,
    PlanPatch,
    TaskSpec,
)
from flowfix_agent.planning.registry import WorkerRegistry
from flowfix_agent.planning.runtime import PlanningRuntime
from flowfix_agent.planning.validation import PlanValidator


# 固定 Planner：单个诊断任务。
class SingleDiagnosisPlanner:
    async def plan(self, incident):
        return PlanDraft(
            plan_id="plan-1",
            tasks=[
                TaskSpec(
                    task_id="diagnose",
                    description="diagnose",
                    required_role="diagnosis",
                    allowed_capabilities={"knowledge.search"},
                )
            ],
        )


# 始终失败的 Worker：无论诊断还是恢复任务都抛错。
class FailingWorker:
    worker_id = "diagnosis"

    async def execute(self, incident, task, dependency_artifacts, *, plan_version=1):
        raise RuntimeError("synthetic persistent worker failure")


# 成功恢复的 Worker：恢复任务产出制品。
class RecoveryWorker:
    worker_id = "recovery"

    async def execute(self, incident, task, dependency_artifacts, *, plan_version=1):
        return Artifact(
            artifact_id=f"artifact-{task.task_id}",
            task_id=task.task_id,
            plan_version=plan_version,
            worker_id=self.worker_id,
            payload={},
            confidence=0.9,
        )


# 失败兜底 Replanner：取消失败任务并新增 recovery 任务。
class RecoveryReplanner:
    async def replan(self, incident, plan, failed_task_ids, *, trigger=None):
        return PlanPatch(
            cancel_task_ids=[*failed_task_ids],
            add_tasks=[
                TaskSpec(
                    task_id="recovery",
                    description="collect alternative evidence",
                    required_role="recovery",
                )
            ],
            expected_plan_version=plan.version,
        )


def _incident(incident_id: str) -> IncidentContext:
    return IncidentContext(
        incident_id=incident_id,
        tenant_id="tenant-1",
        thread_id="thread-1",
        goal="find cause",
        trace_id="trace-1",
    )


def _runtime(store, *, max_replans: int) -> PlanningRuntime:
    registry = WorkerRegistry()
    registry.register("diagnosis", FailingWorker())
    registry.register("recovery", FailingWorker())
    return PlanningRuntime(
        SingleDiagnosisPlanner(),
        PlanController(store, PlanValidator()),
        registry,
        store,
        RecoveryReplanner(),
        max_replans=max_replans,
    )


# 验证 max_replans=2 时允许两次重规划，第三次失败才 FAIL。
async def test_max_replans_allows_two_replans_then_fails(tmp_path):
    store = SQLiteTaskArtifactStore(tmp_path / "max2.db")
    result = await _runtime(store, max_replans=2).run(_incident("i1"))

    assert result.status == "failed"
    assert result.replan_count == 2


# 验证默认 max_replans=1 时一次重规划后再次失败即 FAIL（向后兼容）。
async def test_default_max_replans_single_then_fails(tmp_path):
    store = SQLiteTaskArtifactStore(tmp_path / "max1.db")
    result = await _runtime(store, max_replans=1).run(_incident("i2"))

    assert result.status == "failed"
    assert result.replan_count == 1


# 验证 max_replans=2 且恢复任务成功时正常完成，不触发第二次重规划。
async def test_max_replans_allows_success_within_budget(tmp_path):
    store = SQLiteTaskArtifactStore(tmp_path / "max2ok.db")
    registry = WorkerRegistry()
    registry.register("diagnosis", FailingWorker())
    registry.register("recovery", RecoveryWorker())
    runtime = PlanningRuntime(
        SingleDiagnosisPlanner(),
        PlanController(store, PlanValidator()),
        registry,
        store,
        RecoveryReplanner(),
        max_replans=2,
    )

    result = await runtime.run(_incident("i3"))

    assert result.status == "completed"
    assert result.replan_count == 1
