from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from flowfix_agent.api.routes import router
from flowfix_agent.core.errors import FlowFixError
from flowfix_agent.investigation.loop import InvestigationLoop
from flowfix_agent.investigation.models import AgentDecision, StopReason
from flowfix_agent.memory.task_artifact import SQLiteTaskArtifactStore
from flowfix_agent.planning.controller import PlanController
from flowfix_agent.planning.models import Artifact, PlanDraft, TaskSpec
from flowfix_agent.planning.registry import WorkerRegistry
from flowfix_agent.planning.runtime import PlanningRuntime
from flowfix_agent.planning.validation import PlanValidator
from flowfix_agent.tools import ToolCall, ToolGateway, ToolRegistry, ToolResolver
from flowfix_agent.tools.providers import FakeMCPProvider
from flowfix_agent.tools.providers.retrieval import knowledge_search_spec


# 构建仅含路由与领域异常映射的最小应用，注入 stub container，避免真实凭据/ES。
def _build_app(container) -> FastAPI:
    application = FastAPI()
    application.include_router(router)
    application.state.container = container

    @application.exception_handler(FlowFixError)
    async def handle_domain_error(request, exc: FlowFixError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"error": type(exc).__name__, "message": str(exc)},
        )

    return application


class FakePlanner:
    # 返回仅含 diagnosis 任务的固定计划。
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


class FakeWorker:
    def __init__(self, worker_id: str) -> None:
        self.worker_id = worker_id

    async def execute(self, incident, task, dependency_artifacts, *, plan_version=1):
        return Artifact(
            artifact_id=f"artifact-{task.task_id}",
            task_id=task.task_id,
            plan_version=plan_version,
            worker_id=self.worker_id,
            payload={"diagnosis": {"conclusion": "原因已定位"}},
            confidence=0.9,
        )


def _make_plan_runtime(tmp_path) -> PlanningRuntime:
    store = SQLiteTaskArtifactStore(tmp_path / "planning.db")
    registry = WorkerRegistry()
    registry.register("diagnosis", FakeWorker("diagnosis-1"))
    return PlanningRuntime(
        FakePlanner(), PlanController(store, PlanValidator()), registry, store
    )


class FakeDecision:
    # 第一步调用知识检索，第二步停止并给出结论。
    async def decide(self, request, specs, observations):
        if not observations:
            return AgentDecision(
                tool_call=ToolCall(
                    capability="knowledge.search",
                    arguments={
                        "query": request.goal,
                        "scope": {},
                        "options": {},
                        "trace_id": request.trace_id,
                    },
                    call_id="call-1",
                )
            )
        return AgentDecision(
            conclusion="手册证据支持检查电源。",
            stop_reason=StopReason.COMPLETED,
        )


async def search(arguments: dict[str, Any], context) -> dict[str, Any]:
    return {
        "trace_id": context.trace_id,
        "selected_evidence": [{"source": "manual"}],
        "sufficient": True,
    }


def _make_investigation_loop() -> InvestigationLoop:
    registry = ToolRegistry()
    registry.register(
        knowledge_search_spec(), FakeMCPProvider({"knowledge.search": search})
    )
    return InvestigationLoop(
        FakeDecision(), registry, ToolGateway(ToolResolver(registry))
    )


def test_investigation_plan_returns_planning_result(tmp_path):
    container = SimpleNamespace(planning_runtime=_make_plan_runtime(tmp_path))
    with TestClient(_build_app(container)) as client:
        response = client.post(
            "/v1/investigation/plan",
            headers={"X-Tenant-Id": "tenant-1"},
            json={
                "incident_id": "inc-1",
                "tenant_id": "tenant-1",
                "thread_id": "thread-1",
                "goal": "调查设备异常原因",
                "max_tasks": 8,
                "max_parallel": 2,
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["incident_id"] == "inc-1"
    assert body["status"] == "completed"
    assert body["plan_id"] == "plan-1"
    assert [artifact["task_id"] for artifact in body["artifacts"]] == ["diagnose"]


def test_investigation_plan_rejects_invalid_payload(tmp_path):
    container = SimpleNamespace(planning_runtime=_make_plan_runtime(tmp_path))
    with TestClient(_build_app(container)) as client:
        response = client.post(
            "/v1/investigation/plan",
            json={"tenant_id": "t", "thread_id": "th", "goal": "x"},
        )

    assert response.status_code == 422


def test_investigation_plan_rejects_tenant_mismatch(tmp_path):
    container = SimpleNamespace(planning_runtime=_make_plan_runtime(tmp_path))
    with TestClient(_build_app(container)) as client:
        response = client.post(
            "/v1/investigation/plan",
            headers={"X-Tenant-Id": "tenant-a"},
            json={
                "incident_id": "inc-cross-tenant",
                "tenant_id": "tenant-b",
                "thread_id": "thread-1",
                "goal": "调查设备异常原因",
            },
        )

    assert response.status_code == 403


def test_investigation_run_returns_investigation_result():
    container = SimpleNamespace(investigation_loop=_make_investigation_loop())
    with TestClient(_build_app(container)) as client:
        response = client.post(
            "/v1/investigation/run",
            headers={"X-Tenant-Id": "tenant-1"},
            json={
                "incident_id": "inc-1",
                "tenant_id": "tenant-1",
                "thread_id": "thread-1",
                "goal": "调查设备 DEV-1 断电原因",
                "allowed_capabilities": ["knowledge.search"],
                "max_steps": 6,
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["incident_id"] == "inc-1"
    assert body["stop_reason"] == "completed"
    assert body["steps"] == 2
    assert body["evidence_refs"] == ["call-1"]


def test_investigation_run_rejects_tenant_mismatch():
    container = SimpleNamespace(investigation_loop=_make_investigation_loop())
    with TestClient(_build_app(container)) as client:
        response = client.post(
            "/v1/investigation/run",
            headers={"X-Tenant-Id": "tenant-a"},
            json={
                "incident_id": "inc-cross-tenant",
                "tenant_id": "tenant-b",
                "thread_id": "thread-1",
                "goal": "调查设备 DEV-1 断电原因",
                "allowed_capabilities": ["knowledge.search"],
            },
        )

    assert response.status_code == 403


def test_investigation_run_rejects_invalid_payload():
    container = SimpleNamespace(investigation_loop=_make_investigation_loop())
    with TestClient(_build_app(container)) as client:
        response = client.post(
            "/v1/investigation/run",
            json={"tenant_id": "t", "thread_id": "th", "goal": "x"},
        )

    assert response.status_code == 422
