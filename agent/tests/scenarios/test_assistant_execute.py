from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from flowfix_agent.api.routes import router
from flowfix_agent.assistant.service import AssistantService
from flowfix_agent.core.errors import FlowFixError
from flowfix_agent.core.models import RequestScope
from flowfix_agent.dispatch.runtime.models import RuntimeResult, RuntimeStatus
from flowfix_agent.investigation.models import (
    InvestigationResult,
    StopReason,
)
from flowfix_agent.memory.conversation import ConversationService, SQLiteConversationStore
from flowfix_agent.memory.task_artifact import SQLiteTaskArtifactStore
from flowfix_agent.planning.controller import PlanController
from flowfix_agent.planning.models import Artifact, PlanDraft, TaskSpec
from flowfix_agent.planning.registry import WorkerRegistry
from flowfix_agent.planning.runtime import PlanningRuntime
from flowfix_agent.planning.validation import PlanValidator
from flowfix_agent.qa.models import QAResult, ValidationResult
from flowfix_agent.retrieval.models import EvidenceBundle, RetrievalMode
from flowfix_agent.routing.models import (
    ExtractedEntities,
    RouteDecision,
    RouteType,
)
from flowfix_agent.routing.service import RequestRouter


# 构建仅含路由与领域异常映射的最小应用，注入 stub container。
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


class FakeRouter:
    # 固定返回预设路由决策，用于覆盖四分支编排。
    def __init__(self, decision: RouteDecision) -> None:
        self.decision = decision

    def route(self, message: str, thread_id: str | None = None) -> RouteDecision:
        return self.decision


class FakeQA:
    def __init__(self, result: QAResult) -> None:
        self.result = result
        self.calls = 0
        self.trace_id = None

    async def run(
        self,
        question,
        *,
        scope,
        options,
        conversation_namespace,
        end_conversation,
        trace_id=None,
    ):
        self.calls += 1
        self.trace_id = trace_id
        return self.result


class FakeDispatchRuntime:
    def __init__(self, result: RuntimeResult) -> None:
        self.result = result
        self.started: list = []

    async def start(self, runtime_input):
        self.started.append(runtime_input)
        return self.result


class FakeProposalDispatch:
    def __init__(self, result: RuntimeResult) -> None:
        self.result = result
        self.transferred: list = []

    async def transfer(self, proposal, *, tenant_id, context=None):
        self.transferred.append(proposal)
        return self.result


class FakeInvestigationLoop:
    def __init__(self) -> None:
        self.requests = []

    async def run(self, request):
        self.requests.append(request)
        return InvestigationResult(
            incident_id=request.incident_id,
            trace_id=request.trace_id,
            conclusion="单 Agent 已完成只读调查。",
            observations=[],
            evidence_refs=[],
            stop_reason=StopReason.COMPLETED,
            steps=2,
        )


def _decision(
    route_type: RouteType,
    *,
    work_order_id: str | None = None,
    device_id: str | None = None,
    missing_fields: list[str] | None = None,
) -> RouteDecision:
    return RouteDecision(
        route_type=route_type,
        confidence=0.9,
        reason_code="test",
        extracted_entities=ExtractedEntities(
            work_order_id=work_order_id, device_id=device_id
        ),
        missing_fields=missing_fields or [],
        thread_id="thread-1",
        trace_id=f"trace-{route_type.value.lower()}",
    )


def _make_qa_result(trace_id: str = "trace-knowledge_qa") -> QAResult:
    return QAResult(
        trace_id=trace_id,
        question="测试问题",
        answer="参考手册恢复步骤。",
        refused=False,
        citations=[],
        evidence=[],
        retrieval=EvidenceBundle(
            trace_id=trace_id,
            original_query="测试问题",
            retrieval_query="测试问题",
            mode=RetrievalMode.HYBRID,
            scope=RequestScope(),
            candidates=[],
            selected_evidence=[],
            budget_used=0,
            sufficient=True,
            latency_ms=1.0,
        ),
        validation=ValidationResult(valid=True),
        generator_model="test-model",
    )


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


def _make_planning_runtime(tmp_path) -> PlanningRuntime:
    store = SQLiteTaskArtifactStore(tmp_path / "planning.db")
    registry = WorkerRegistry()
    registry.register("diagnosis", FakeWorker("diagnosis-1"))
    return PlanningRuntime(
        FakePlanner(), PlanController(store, PlanValidator()), registry, store
    )


def _execute(container, payload: dict, *, headers: dict | None = None) -> dict:
    with TestClient(_build_app(container)) as client:
        response = client.post("/v1/assistant/execute", json=payload, headers=headers)
    assert response.status_code == 200
    return response.json()


def test_assistant_execute_needs_clarification_branch():
    router = FakeRouter(
        _decision(
            RouteType.NEEDS_CLARIFICATION,
            missing_fields=["intent"],
        )
    )
    service = AssistantService(router, FakeQA(_make_qa_result()), None, None, None, None, None)
    body = _execute(SimpleNamespace(assistant=service), {"message": "帮我派单"})

    assert body["route_type"] == "NEEDS_CLARIFICATION"
    assert body["outcome"] == "needs_input"
    assert body["missing_fields"] == ["intent"]
    assert body["qa"] is None and body["dispatch"] is None


def test_assistant_execute_qa_branch():
    qa = FakeQA(_make_qa_result())
    router = FakeRouter(_decision(RouteType.KNOWLEDGE_QA))
    service = AssistantService(router, qa, None, None, None, None, None)
    body = _execute(SimpleNamespace(assistant=service), {"message": "如何恢复设备"})

    assert body["route_type"] == "KNOWLEDGE_QA"
    assert body["outcome"] == "completed"
    assert body["message"] == "参考手册恢复步骤。"
    assert qa.calls == 1
    assert qa.trace_id == body["trace_id"] == body["qa"]["trace_id"]
    assert body["qa"]["answer"] == "参考手册恢复步骤。"


def test_assistant_execute_dispatch_branch_requires_work_order():
    router = FakeRouter(_decision(RouteType.DIRECT_DISPATCH, work_order_id="WO-1001"))
    result = RuntimeResult(
        thread_id="thread-1",
        status=RuntimeStatus.AWAITING_APPROVAL,
        interrupted=True,
    )
    dispatch = FakeDispatchRuntime(result)
    service = AssistantService(router, None, dispatch, None, None, None, None)
    body = _execute(SimpleNamespace(assistant=service), {"message": "对 WO-1001 派单"})

    assert body["route_type"] == "DIRECT_DISPATCH"
    assert body["outcome"] == "needs_approval"
    assert body["execution_mode"] == "java_dispatch_handoff"
    assert body["next_action"]["type"] == "trigger_java_dispatch"
    assert body["next_action"]["continuation_id"] == "WO-1001"
    assert dispatch.started == []


def test_assistant_execute_dispatch_branch_missing_work_order_is_clarification():
    router = FakeRouter(_decision(RouteType.DIRECT_DISPATCH, work_order_id=None))
    dispatch = FakeDispatchRuntime(
        RuntimeResult(thread_id="t", status=RuntimeStatus.VERIFIED)
    )
    service = AssistantService(router, None, dispatch, None, None, None, None)
    body = _execute(SimpleNamespace(assistant=service), {"message": "帮我派单"})

    assert body["outcome"] == "needs_input"
    assert body["missing_fields"] == ["work_order_id"]
    assert dispatch.started == []


def test_assistant_execute_investigation_proposal_hands_off_to_java(tmp_path):
    router = FakeRouter(
        _decision(
            RouteType.INCIDENT_INVESTIGATION,
            work_order_id="WO-1002",
            device_id="DEV-1002",
        )
    )
    planning = _make_planning_runtime(tmp_path)
    proposal_dispatch = FakeProposalDispatch(None)
    service = AssistantService(
        router, None, None, planning, proposal_dispatch, None, None
    )
    body = _execute(
        SimpleNamespace(assistant=service),
        {"message": "调查设备 DEV-1002 的 WO-1002 异常"},
    )

    assert body["route_type"] == "INCIDENT_INVESTIGATION"
    assert body["outcome"] == "needs_approval"
    assert body["planning"]["status"] == "completed"
    assert proposal_dispatch.transferred == []
    assert body["dispatch"] is None
    assert body["execution_mode"] == "multi_agent_planning"
    assert body["next_action"]["type"] == "trigger_java_dispatch"
    assert body["next_action"]["continuation_id"] == "WO-1002"


def test_assistant_execute_investigation_branch_without_proposal_is_completed(tmp_path):
    router = FakeRouter(
        _decision(RouteType.INCIDENT_INVESTIGATION, device_id="DEV-1003")
    )
    planning = _make_planning_runtime(tmp_path)
    investigation = FakeInvestigationLoop()
    service = AssistantService(
        router, None, None, planning, FakeProposalDispatch(None), None, None,
        investigation,
    )
    body = _execute(
        SimpleNamespace(assistant=service), {"message": "调查设备 DEV-1003 异常"}
    )

    assert body["route_type"] == "INCIDENT_INVESTIGATION"
    assert body["outcome"] == "completed"
    assert body["execution_mode"] == "single_agent"
    assert body["planning"] is None
    assert body["investigation"]["steps"] == 2
    assert investigation.requests[0].max_steps == 4


def test_complex_investigation_uses_multi_agent_planning(tmp_path):
    router = FakeRouter(
        _decision(RouteType.INCIDENT_INVESTIGATION, device_id="DEV-1004")
    )
    planning = _make_planning_runtime(tmp_path)
    investigation = FakeInvestigationLoop()
    service = AssistantService(
        router, None, None, planning, FakeProposalDispatch(None), None, None,
        investigation,
    )

    body = _execute(
        SimpleNamespace(assistant=service),
        {"message": "调查设备 DEV-1004 大面积停机并分析影响范围"},
    )

    assert body["execution_mode"] == "multi_agent_planning"
    assert body["planning"]["status"] == "completed"
    assert body["investigation"] is None
    assert investigation.requests == []


def test_assistant_clarification_continues_original_intent(tmp_path):
    conversation = ConversationService(SQLiteConversationStore(tmp_path / "conversation.db"))
    planning = _make_planning_runtime(tmp_path)
    service = AssistantService(
        RequestRouter(), None, None, planning, FakeProposalDispatch(None), conversation, None
    )
    container = SimpleNamespace(assistant=service)

    first = _execute(
        container,
        {
            "message": "帮我调查异常",
            "thread_id": "thread-1",
        },
        headers={"X-Principal-Id": "user-1"},
    )
    second = _execute(
        container,
        {
            "message": "设备 DEV-001",
            "thread_id": "thread-1",
        },
        headers={"X-Principal-Id": "user-1"},
    )

    assert first["outcome"] == "needs_input"
    assert first["route_type"] == "INCIDENT_INVESTIGATION"
    assert first["missing_fields"] == ["device_id"]
    assert first["next_action"]["type"] == "provide_fields"
    assert second["route_type"] == "INCIDENT_INVESTIGATION"
    assert second["outcome"] == "completed"


def test_dispatch_chain_owns_work_order_validation_and_continuation(tmp_path):
    conversation = ConversationService(SQLiteConversationStore(tmp_path / "dispatch-chat.db"))
    dispatch = FakeDispatchRuntime(
        RuntimeResult(thread_id="dispatch-1", status=RuntimeStatus.VERIFIED)
    )
    service = AssistantService(
        RequestRouter(), None, dispatch, None, None, conversation, None
    )
    container = SimpleNamespace(assistant=service)
    headers = {"X-Principal-Id": "user-1"}

    first = _execute(
        container,
        {"message": "帮我派单", "thread_id": "thread-dispatch"},
        headers=headers,
    )
    second = _execute(
        container,
        {"message": "工单 WO-1009", "thread_id": "thread-dispatch"},
        headers=headers,
    )

    assert first["route_type"] == "DIRECT_DISPATCH"
    assert first["outcome"] == "needs_input"
    assert first["missing_fields"] == ["work_order_id"]
    assert second["outcome"] == "needs_approval"
    assert second["execution_mode"] == "java_dispatch_handoff"
    assert second["next_action"]["continuation_id"] == "WO-1009"
    assert dispatch.started == []
