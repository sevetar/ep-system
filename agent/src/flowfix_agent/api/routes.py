from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

from flowfix_agent.api.auth import get_principal, require_permission
from flowfix_agent.api.schemas import (
    AssistantExecuteRequest,
    AssistantExecuteResponse,
    AssistantRouteRequest,
    DispatchResumeRequest,
    DispatchStartRequest,
    HealthResponse,
    IngestRequest,
    IngestResponse,
    InvestigationPlanRequest,
    InvestigationResponse,
    InvestigationRunRequest,
    KnowledgeStatusResponse,
    PlanningResponse,
    PlanningResumeRequest,
    QARequest,
    QAResponse,
    RetrievalRequest,
    RetrievalResponse,
    WorkOrderKnowledgeEventStatusResponse,
    WorkOrderKnowledgeRevokeRequest,
    WorkOrderKnowledgeRevokeResponse,
    plan_request_to_incident,
    run_request_to_investigation,
)
from flowfix_agent.bootstrap.container import AppContainer
from flowfix_agent.core.models import Principal
from flowfix_agent.dispatch.domain.models import DispatchRequest
from flowfix_agent.dispatch.runtime.models import (
    DispatchRuntimeInput,
    RequestContext,
    RuntimeResult,
)
from flowfix_agent.memory.conversation import ConversationNamespace
from flowfix_agent.messaging.models import DispatchEvent
from flowfix_agent.routing.models import RouteDecision

router = APIRouter()
PrincipalDep = Annotated[Principal, Depends(get_principal)]


# 从 FastAPI 应用状态中取得依赖容器。
def get_container(request: Request) -> AppContainer:
    return request.app.state.container


# 返回服务进程的存活状态。
@router.get("/health/live", response_model=HealthResponse, tags=["health"])
async def live(request: Request) -> HealthResponse:
    container = get_container(request)
    return HealthResponse(status="ok", service=container.settings.app_name)


# 检查 Elasticsearch 与 Java 派单依赖后返回服务就绪状态。
@router.get("/health/ready", response_model=HealthResponse, tags=["health"])
async def ready(request: Request) -> HealthResponse:
    container = get_container(request)
    elasticsearch = "ok" if await container.index.ping() else "unavailable"
    java_dispatch = "ok" if await container.java_dispatch.health() else "unavailable"
    dependencies = {"elasticsearch": elasticsearch, "java_dispatch": java_dispatch}
    if container.rabbitmq is not None:
        dependencies["rabbitmq"] = "ok" if await container.rabbitmq.health() else "unavailable"
    if container.knowledge_rabbitmq is not None:
        dependencies["work_order_knowledge"] = (
            "ok" if await container.knowledge_rabbitmq.health() else "unavailable"
        )
    return HealthResponse(
        status="ok" if all(value == "ok" for value in dependencies.values()) else "degraded",
        service=container.settings.app_name,
        dependencies=dependencies,
    )


# 接收知识路径并执行版本化摄取任务。
@router.post(
    "/v1/knowledge/ingest",
    response_model=IngestResponse,
    tags=["knowledge"],
)
async def ingest(
    request: Request,
    payload: IngestRequest,
    principal: PrincipalDep,
) -> IngestResponse:
    require_permission(principal, "knowledge:write")
    container = get_container(request)
    report = await container.ingestion.ingest(
        payload.paths,
        payload.source_type,
        payload.recreate_index,
    )
    return IngestResponse.model_validate(report)


# 汇总当前激活知识源、分块数量和版本信息。
@router.get(
    "/v1/knowledge/status",
    response_model=KnowledgeStatusResponse,
    tags=["knowledge"],
)
async def knowledge_status(
    request: Request, principal: PrincipalDep
) -> KnowledgeStatusResponse:
    require_permission(principal, "knowledge:read")
    container = get_container(request)
    records = await container.catalog.list_active()
    chunks = sum(record.indexed_chunks for record in records)
    return KnowledgeStatusResponse(
        index=container.index.index_name,
        sources=len(records),
        chunks=chunks,
        active_versions={record.source_id: record.active_version for record in records},
    )


@router.get(
    "/v1/knowledge/work-orders/events/{event_id}",
    response_model=WorkOrderKnowledgeEventStatusResponse,
    tags=["knowledge"],
)
async def work_order_knowledge_event_status(
    event_id: str, request: Request, principal: PrincipalDep
) -> WorkOrderKnowledgeEventStatusResponse:
    require_permission(principal, "knowledge:read")
    container = get_container(request)
    record = await container.work_order_knowledge_ingestion.get_status(event_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="event not found")
    if record.tenant_id != principal.tenant_id and "knowledge:admin" not in principal.permissions:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="tenant mismatch")
    return WorkOrderKnowledgeEventStatusResponse.model_validate(record.model_dump())


@router.post(
    "/v1/knowledge/work-orders/{work_order_id}/revoke",
    response_model=WorkOrderKnowledgeRevokeResponse,
    tags=["knowledge"],
)
async def revoke_work_order_knowledge(
    work_order_id: str,
    payload: WorkOrderKnowledgeRevokeRequest,
    request: Request,
    principal: PrincipalDep,
) -> WorkOrderKnowledgeRevokeResponse:
    require_permission(principal, "knowledge:write")
    if payload.tenant_id != principal.tenant_id and "knowledge:admin" not in principal.permissions:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="tenant mismatch")
    container = get_container(request)
    deleted = await container.work_order_knowledge_ingestion.revoke(
        payload.tenant_id, work_order_id, payload.reason
    )
    return WorkOrderKnowledgeRevokeResponse(
        source_id=container.work_order_knowledge_ingestion.source_id(
            payload.tenant_id, work_order_id
        ),
        deleted_chunks=deleted,
    )


# 根据请求范围和检索选项返回结构化证据包。
@router.post(
    "/v1/retrieval/search",
    response_model=RetrievalResponse,
    tags=["retrieval"],
)
async def retrieve(
    request: Request,
    payload: RetrievalRequest,
    principal: PrincipalDep,
) -> RetrievalResponse:
    _require_tenant(principal, payload.scope.tenant_id)
    container = get_container(request)
    bundle = await container.retrieval.retrieve(payload.query, payload.scope, payload.options)
    return RetrievalResponse.model_validate(bundle)


# 执行检索、生成、引用校验和拒答组成的完整问答流程。
@router.post("/v1/qa/query", response_model=QAResponse, tags=["qa"])
async def query(
    request: Request,
    payload: QARequest,
    principal: PrincipalDep,
) -> QAResponse:
    _require_tenant(principal, payload.scope.tenant_id)
    container = get_container(request)
    namespace = None
    if payload.thread_id:
        namespace = ConversationNamespace(
            tenant_id=payload.scope.tenant_id,
            user_id=principal.user_id,
            thread_id=payload.thread_id,
        )
    result = await container.qa.run(
        payload.query,
        payload.scope,
        payload.options,
        conversation_namespace=namespace,
        end_conversation=payload.end_conversation,
    )
    # QAWorkflow 返回父类 QAResult；Pydantic 不会把父类实例直接当作子类
    # QAResponse 校验，先转成普通数据再构造响应，避免成功生成后在 API 边界返回 500。
    return QAResponse.model_validate(result.model_dump())


# 将用户消息路由到对应的处理链路并返回路由决策。
@router.post("/v1/assistant/route", response_model=RouteDecision, tags=["assistant"])
async def route_assistant(
    request: Request,
    payload: AssistantRouteRequest,
    principal: PrincipalDep,
) -> RouteDecision:
    return await get_container(request).request_router.route_async(
        payload.message, thread_id=payload.thread_id
    )


# 统一入口：按路由决策同步编排三条链路并返回执行结果。
@router.post(
    "/v1/assistant/execute",
    response_model=AssistantExecuteResponse,
    tags=["assistant"],
)
async def execute_assistant(
    request: Request,
    payload: AssistantExecuteRequest,
    principal: PrincipalDep,
) -> AssistantExecuteResponse:
    if payload.scope:
        _require_tenant(principal, payload.scope.tenant_id)
    execution = await get_container(request).assistant.execute(
        payload.message,
        thread_id=payload.thread_id,
        user_id=principal.user_id,
        tenant_id=principal.tenant_id,
        scope=payload.scope,
    )
    # 子类响应模型只接受 dict 或自身实例，先转 dict 再重建以兼容父类返回值。
    return AssistantExecuteResponse.model_validate(execution.model_dump())


# 运行多 Agent 调查规划链并返回计划与制品。
@router.post(
    "/v1/investigation/plan",
    response_model=PlanningResponse,
    tags=["investigation"],
)
async def plan_investigation(
    request: Request,
    payload: InvestigationPlanRequest,
    principal: PrincipalDep,
) -> PlanningResponse:
    require_permission(principal, "planning:write")
    _require_tenant(principal, payload.tenant_id)
    trace_id = uuid.uuid4().hex
    incident = plan_request_to_incident(payload, trace_id)
    result = await get_container(request).planning_runtime.run(incident)
    return PlanningResponse.model_validate(result.model_dump())


# 运行单 Agent 只读调查循环并返回结论与证据。
@router.post(
    "/v1/investigation/run",
    response_model=InvestigationResponse,
    tags=["investigation"],
)
async def run_investigation(
    request: Request,
    payload: InvestigationRunRequest,
    principal: PrincipalDep,
) -> InvestigationResponse:
    require_permission(principal, "planning:read")
    _require_tenant(principal, payload.tenant_id)
    trace_id = uuid.uuid4().hex
    investigation = run_request_to_investigation(
        payload,
        trace_id,
        default_max_steps=getattr(
            getattr(get_container(request), "settings", None),
            "investigation_max_steps",
            6,
        ),
    )
    result = await get_container(request).investigation_loop.run(investigation)
    return InvestigationResponse.model_validate(result.model_dump())


# 启动一次受控派单流程并返回运行时结果。
@router.post("/v1/dispatch/start", response_model=RuntimeResult, tags=["dispatch"])
async def start_dispatch(
    request: Request,
    payload: DispatchStartRequest,
    principal: PrincipalDep,
) -> RuntimeResult:
    require_permission(principal, "dispatch:write")
    container = get_container(request)
    runtime_input = DispatchRuntimeInput(
        request=DispatchRequest(
            dispatch_id=payload.dispatch_id,
            event_id=payload.event_id,
            tenant_id=principal.tenant_id,
            trigger=payload.trigger,
        ),
        work_order_id=payload.work_order_id,
        context=RequestContext(
            trace_id=payload.trace_id,
            tenant_id=principal.tenant_id,
            event_id=payload.event_id,
            permissions=sorted(principal.permissions),
            deadline=datetime.now(UTC) + timedelta(seconds=payload.deadline_seconds),
            approval_expires_at=datetime.now(UTC)
            + timedelta(seconds=container.settings.dispatch_approval_ttl_seconds),
            execution_timeout_seconds=payload.deadline_seconds,
        ),
    )
    return await container.dispatch_runtime.start(runtime_input)


@router.post("/v1/dispatch/events", status_code=202, tags=["dispatch"])
async def publish_dispatch_event(
    request: Request,
    payload: DispatchEvent,
    principal: PrincipalDep,
) -> dict[str, str]:
    """把派单请求可靠发布到 RabbitMQ；消费结果通过 outcome routing key 返回。"""
    require_permission(principal, "dispatch:write")
    _require_tenant(principal, payload.tenant_id)
    bridge = get_container(request).rabbitmq
    if bridge is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="RabbitMQ dispatch chain is disabled",
        )
    await bridge.publish_request(payload)
    return {"status": "accepted", "event_id": payload.event_id}


@router.post(
    "/v1/dispatch/{thread_id}/resume", response_model=RuntimeResult, tags=["dispatch"]
)
# 携带人工审批决策恢复被挂起的派单流程。
async def resume_dispatch(
    request: Request,
    thread_id: str,
    payload: DispatchResumeRequest,
    principal: PrincipalDep,
) -> RuntimeResult:
    require_permission(principal, "dispatch:approve")
    return await get_container(request).dispatch_runtime.resume(
        thread_id,
        payload.to_approval(principal.user_id),
        tenant_id=principal.tenant_id,
    )


@router.post(
    "/v1/dispatch/{thread_id}/retry", response_model=RuntimeResult, tags=["dispatch"]
)
# 重试一次失败的派单流程。
async def retry_dispatch(
    request: Request,
    thread_id: str,
    principal: PrincipalDep,
) -> RuntimeResult:
    require_permission(principal, "dispatch:write")
    return await get_container(request).dispatch_runtime.retry(
        thread_id, tenant_id=principal.tenant_id
    )


@router.get(
    "/v1/dispatch/{thread_id}/status", response_model=RuntimeResult, tags=["dispatch"]
)
# 查询指定线程当前派单的运行时状态。
async def dispatch_status(
    request: Request,
    thread_id: str,
    principal: PrincipalDep,
) -> RuntimeResult:
    require_permission(principal, "dispatch:read")
    return await get_container(request).dispatch_runtime.status(
        thread_id, tenant_id=principal.tenant_id
    )


@router.get("/v1/dispatch/{thread_id}/history", tags=["dispatch"])
# 返回指定线程派单流程的状态变更历史。
async def dispatch_history(
    request: Request,
    thread_id: str,
    principal: PrincipalDep,
) -> list[dict]:
    require_permission(principal, "dispatch:read")
    history = await get_container(request).dispatch_runtime.state_history(
        thread_id, tenant_id=principal.tenant_id
    )
    return [
        {
            "status": item.get("runtime_status"),
            "errors": item.get("errors", []),
            "assignment_outcome": item.get("assignment_outcome"),
        }
        for item in history
    ]


@router.post(
    "/v1/planning/{thread_id}/resume",
    response_model=PlanningResponse,
    tags=["investigation"],
)
async def resume_planning(
    request: Request,
    thread_id: str,
    payload: PlanningResumeRequest,
    principal: PrincipalDep,
) -> PlanningResponse:
    require_permission(principal, "planning:write")
    result = await get_container(request).planning_runtime.resume(
        thread_id, payload, tenant_id=principal.tenant_id
    )
    return PlanningResponse.model_validate(result.model_dump())


@router.get(
    "/v1/planning/{thread_id}/status",
    response_model=PlanningResponse,
    tags=["investigation"],
)
async def planning_status(
    request: Request,
    thread_id: str,
    principal: PrincipalDep,
) -> PlanningResponse:
    require_permission(principal, "planning:read")
    result = await get_container(request).planning_runtime.status(
        thread_id, tenant_id=principal.tenant_id
    )
    return PlanningResponse.model_validate(result.model_dump())


def _require_tenant(principal: Principal, tenant_id: str) -> None:
    if principal.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="request tenant does not match authenticated principal",
        )
