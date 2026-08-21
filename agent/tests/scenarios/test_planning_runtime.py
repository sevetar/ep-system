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


class FakePlanner:
    async def plan(self, incident):
        return PlanDraft(
            plan_id="plan-1",
            tasks=[
                TaskSpec(
                    task_id="diagnose",
                    description="diagnose",
                    required_role="diagnosis",
                    allowed_capabilities={"knowledge.search"},
                ),
                TaskSpec(
                    task_id="impact",
                    description="impact",
                    required_role="impact_safety",
                    dependencies=["diagnose"],
                ),
            ],
        )


class FakeWorker:
    def __init__(self, worker_id):
        self.worker_id = worker_id
        self.calls = 0

    async def execute(self, incident, task, dependency_artifacts, *, plan_version=1):
        self.calls += 1
        return Artifact(
            artifact_id=f"artifact-{task.task_id}",
            task_id=task.task_id,
            plan_version=plan_version,
            worker_id=self.worker_id,
            payload={"dependency_count": len(dependency_artifacts)},
            confidence=0.9,
        )


class FailingWorker:
    worker_id = "failing-1"

    async def execute(self, incident, task, dependency_artifacts, *, plan_version=1):
        raise RuntimeError("synthetic worker failure")


class RecoveryReplanner:
    async def replan(self, incident, plan, failed_task_ids, *, trigger=None):
        return PlanPatch(
            cancel_task_ids=[*failed_task_ids, "impact"],
            add_tasks=[
                TaskSpec(
                    task_id="recovery",
                    description="collect alternative evidence",
                    required_role="recovery",
                )
            ],
            expected_plan_version=plan.version,
        )


async def test_five_node_runtime_executes_dynamic_dag_and_persists_artifacts(tmp_path):
    store = SQLiteTaskArtifactStore(tmp_path / "planning.db")
    diagnosis = FakeWorker("diagnosis-1")
    impact = FakeWorker("impact-1")
    registry = WorkerRegistry()
    registry.register("diagnosis", diagnosis)
    registry.register("impact_safety", impact)
    runtime = PlanningRuntime(
        FakePlanner(), PlanController(store, PlanValidator()), registry, store
    )

    result = await runtime.run(
        IncidentContext(
            incident_id="incident-1",
            tenant_id="tenant-1",
            thread_id="thread-1",
            goal="find cause and impact",
            trace_id="trace-1",
        )
    )

    assert result.status == "completed"
    assert [artifact.task_id for artifact in result.artifacts] == ["diagnose", "impact"]
    assert result.artifacts[1].payload["dependency_count"] == 1
    assert diagnosis.calls == impact.calls == 1
    assert len(store.list_plan("tenant-1", "thread-1", "plan-1")) == 3


async def test_runtime_applies_one_versioned_replan_after_worker_failure(tmp_path):
    store = SQLiteTaskArtifactStore(tmp_path / "replan.db")
    registry = WorkerRegistry()
    registry.register("diagnosis", FailingWorker())
    registry.register("impact_safety", FakeWorker("unused-impact"))
    registry.register("recovery", FakeWorker("recovery-1"))
    runtime = PlanningRuntime(
        FakePlanner(),
        PlanController(store, PlanValidator()),
        registry,
        store,
        RecoveryReplanner(),
    )

    result = await runtime.run(
        IncidentContext(
            incident_id="incident-2",
            tenant_id="tenant-1",
            thread_id="thread-2",
            goal="recover",
            trace_id="trace-2",
        )
    )

    assert result.status == "completed"
    assert result.plan_version == 2
    assert result.replan_count == 1
    assert [item.task_id for item in result.artifacts] == ["recovery"]
    # Replan 后执行的 recovery 制品必须归属新版本，版本门控才能正确过滤。
    assert result.artifacts[0].plan_version == 2
