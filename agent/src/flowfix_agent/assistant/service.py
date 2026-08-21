from __future__ import annotations

from flowfix_agent.assistant.models import (
    AssistantExecution,
    AssistantOutcome,
    NextAction,
)
from flowfix_agent.core.errors import RequestAuthorizationError
from flowfix_agent.core.models import RequestScope
from flowfix_agent.dispatch.runtime.ports import DispatchRuntimePort
from flowfix_agent.investigation.models import InvestigationRequest, StopReason
from flowfix_agent.memory.conversation import ConversationNamespace, PendingTurn
from flowfix_agent.planning.models import IncidentContext
from flowfix_agent.qa.workflow import QAWorkflow
from flowfix_agent.retrieval.models import RetrievalOptions
from flowfix_agent.routing import RequestRouter
from flowfix_agent.routing.models import RouteType


# 统一入口编排服务：Router 只选链路，本服务按路由结果转调目标链路。
class AssistantService:
    # 注入路由、三条链路运行时与配置，组装编排依赖。
    def __init__(
        self,
        request_router: RequestRouter,
        qa: QAWorkflow,
        dispatch_runtime: DispatchRuntimePort,
        planning_runtime,
        proposal_dispatch,
        conversation,
        settings,
        investigation_loop=None,
    ) -> None:
        self.request_router = request_router
        self.qa = qa
        self.dispatch_runtime = dispatch_runtime
        self.planning_runtime = planning_runtime
        self.proposal_dispatch = proposal_dispatch
        self.conversation = conversation
        self.settings = settings
        self.investigation_loop = investigation_loop

    # 统一编排入口：完成一次请求的完整生命周期。
    # 流程：加载待续回合 → 合并会话上下文 → 路由选链路 → 校验租户 → 按链路类型转调。
    # 本方法只做编排、不执行任何业务写入；真实写入（派单/调查）由目标链路完成。
    # 当信息不全需要人工补充时，把待续状态落库（PendingTurn），等用户下次补全后继续。
    async def execute(
        self,
        message: str,
        *,
        thread_id: str | None = None,
        user_id: str | None = None,
        tenant_id: str = "public",
        scope: RequestScope | None = None,
    ) -> AssistantExecution:
        # 1) 由认证维度派生会话命名空间；user_id 或 thread_id 任一缺失则视为无会话。
        namespace = self._namespace(tenant_id, user_id, thread_id)
        # 2) 加载因信息不全而挂起的待续回合；未开启会话存储时 pending 恒为 None。
        pending = (
            self.conversation.load_pending(namespace)
            if self.conversation and namespace
            else None
        )
        # 3) 有待续回合时，把上一次消息与本次补充拼接后再路由，保证上下文连续。
        routed_message = f"{pending.original_message} {message}" if pending else message
        if pending and pending.route_type:
            # 业务意图已确定：锁定原 route 只重新提取补充实体，避免重复猜测意图。
            decision = await self._route(
                routed_message,
                thread_id=thread_id,
                trace_id=pending.trace_id,
                intent_hint=RouteType(pending.route_type),
            )
        else:
            # 无待续或意图未定：走完整路由（含可能的 LLM 兜底）重新决策。
            decision = await self._route(routed_message, thread_id=thread_id)
        # 4) trace_id 优先沿用待续回合，保证同一会话跨多次交互的追踪链路连续。
        trace_id = pending.trace_id if pending else decision.trace_id
        # 5) 统一作用域校验：传入 scope 的租户必须与认证租户一致，防止跨租户越权。
        effective_scope = scope or RequestScope(tenant_id=tenant_id)
        if effective_scope.tenant_id != tenant_id:
            raise RequestAuthorizationError(
                "request scope tenant does not match authenticated tenant"
            )
        if decision.route_type is RouteType.NEEDS_CLARIFICATION:
            # 6a) 信息不全：把原消息与缺失字段存为待续回合，等用户下次补齐。
            if self.conversation and namespace:
                self.conversation.save_pending(
                    namespace,
                    PendingTurn(
                        original_message=routed_message,
                        missing_fields=decision.missing_fields,
                        # 沿用本次 trace_id，便于用户补全后串回同一条链路。
                        trace_id=pending.trace_id if pending else trace_id,
                        # 意图未定，route_type 置空，下次重新路由。
                        route_type=None,
                    ),
                )
            # 返回 NEEDS_INPUT 并附上需补充字段的输入 Schema；无线程则无法续接。
            return AssistantExecution(
                route_type=decision.route_type,
                trace_id=trace_id,
                outcome=AssistantOutcome.NEEDS_INPUT,
                message="输入信息不完整，请补充必要信息。",
                route_reason_code=decision.reason_code,
                execution_mode="clarification",
                missing_fields=decision.missing_fields,
                next_action=(
                    NextAction(
                        type="provide_fields",
                        continuation_id=thread_id,
                        input_schema={"required": decision.missing_fields},
                        resume_endpoint="/v1/assistant/execute",
                    )
                    if thread_id
                    else None
                ),
            )
        if self.conversation and namespace and pending:
            # 6b) 路由确定可继续执行：清空待续回合，避免下次重复拼接上下文。
            self.conversation.clear_pending(namespace)
        # 7) 按路由结果转调三条专业链路之一：知识问答 / 受控派单 / 调查与规划。
        if decision.route_type is RouteType.KNOWLEDGE_QA:
            return await self._execute_qa(
                routed_message,
                decision.reason_code,
                trace_id,
                effective_scope,
                thread_id,
                user_id,
                tenant_id,
            )
        if decision.route_type is RouteType.DIRECT_DISPATCH:
            return await self._execute_dispatch(
                routed_message, decision, trace_id, tenant_id, namespace
            )
        # 其余（INCIDENT_INVESTIGATION）转入调查与规划链路。
        return await self._execute_investigation(
            routed_message, decision, trace_id, thread_id, tenant_id, namespace
        )

    # 知识问答分支：携带会话上下文调用 QA 工作流。
    async def _execute_qa(
        self,
        message: str,
        route_reason_code: str,
        trace_id: str,
        scope: RequestScope,
        thread_id: str | None,
        user_id: str | None,
        tenant_id: str,
    ) -> AssistantExecution:
        namespace = None
        if user_id and thread_id:
            namespace = ConversationNamespace(
                tenant_id=tenant_id, user_id=user_id, thread_id=thread_id
            )
        result = await self.qa.run(
            message,
            scope=scope,
            options=RetrievalOptions(),
            conversation_namespace=namespace,
            end_conversation=False,
            trace_id=trace_id,
        )
        return AssistantExecution(
            route_type=RouteType.KNOWLEDGE_QA,
            trace_id=trace_id,
            outcome=(AssistantOutcome.REFUSED if result.refused else AssistantOutcome.COMPLETED),
            message=result.answer,
            route_reason_code=route_reason_code,
            execution_mode="qa",
            qa=result,
        )

    # 派单意图分支只返回 Java 受控触发动作；统一自然语言入口不得绕过 Java 鉴权与 Outbox。
    async def _execute_dispatch(
        self,
        message: str,
        decision,
        trace_id: str,
        tenant_id: str,
        namespace: ConversationNamespace | None,
    ) -> AssistantExecution:
        # 1) 取路由决策抽取的工单号；缺失即业务必填字段不全，
        #    落库待续回合并返回 NEEDS_INPUT，等用户补齐后继续。
        work_order_id = decision.extracted_entities.work_order_id
        if not work_order_id:
            return self._business_input_required(
                route_type=RouteType.DIRECT_DISPATCH,
                message=message,
                trace_id=trace_id,
                missing_fields=["work_order_id"],
                prompt="派单请求缺少工单号。",
                namespace=namespace,
            )
        return AssistantExecution(
            route_type=RouteType.DIRECT_DISPATCH,
            trace_id=trace_id,
            outcome=AssistantOutcome.NEEDS_APPROVAL,
            message=f"已识别工单 {work_order_id} 的派单请求，请由管理员确认后经 Java 触发。",
            route_reason_code=decision.reason_code,
            execution_mode="java_dispatch_handoff",
            next_action=NextAction(
                type="trigger_java_dispatch",
                continuation_id=work_order_id,
                input_schema={
                    "required": ["work_order_id", "idempotency_key"],
                    "properties": {"work_order_id": {"const": work_order_id}},
                },
                resume_endpoint=f"/deviceMaintain/{work_order_id}/auto-dispatch",
            ),
        )

    # 调查与规划分支：运行六节点规划，产出派单建议时强制经人工审批转交派单链路。
    async def _execute_investigation(
        self,
        message: str,
        decision,
        trace_id: str,
        thread_id: str | None,
        tenant_id: str,
        namespace: ConversationNamespace | None,
    ) -> AssistantExecution:
        # 1) 取路由决策抽取的设备号；缺失即业务必填字段不全，
        #    落库待续回合并返回 NEEDS_INPUT，等用户补齐后继续。
        device_id = decision.extracted_entities.device_id
        if not device_id:
            return self._business_input_required(
                route_type=RouteType.INCIDENT_INVESTIGATION,
                message=message,
                trace_id=trace_id,
                missing_fields=["device_id"],
                prompt="故障调查请求缺少设备号。",
                namespace=namespace,
            )
        # 2) 简单、低风险、无关联工单的调查优先进入有界 Single-Agent，减少规划开销。
        if self.investigation_loop is not None and self._use_single_agent(message, decision):
            result = await self.investigation_loop.run(
                InvestigationRequest(
                    incident_id=f"inc-{trace_id}",
                    tenant_id=tenant_id,
                    thread_id=thread_id or "anon",
                    goal=message,
                    trace_id=trace_id,
                    allowed_capabilities={"knowledge.search"},
                    max_steps=self._setting("assistant_simple_investigation_max_steps", 4),
                )
            )
            outcome = {
                StopReason.COMPLETED: AssistantOutcome.COMPLETED,
                StopReason.INSUFFICIENT_EVIDENCE: AssistantOutcome.REFUSED,
            }.get(result.stop_reason, AssistantOutcome.FAILED)
            return AssistantExecution(
                route_type=RouteType.INCIDENT_INVESTIGATION,
                trace_id=trace_id,
                outcome=outcome,
                message=result.conclusion,
                route_reason_code=decision.reason_code,
                execution_mode="single_agent",
                investigation=result,
            )

        # 3) 复杂调查组装事故上下文并进入多 Agent Planning。
        #    dispatch_target 记录可选的关联工单，规划产出派单建议时沿用。
        incident = IncidentContext(
            incident_id=f"inc-{trace_id}",
            tenant_id=tenant_id,
            thread_id=thread_id or "anon",
            goal=message,
            trace_id=trace_id,
            device_id=device_id,
            dispatch_target=decision.extracted_entities.work_order_id,
        )

        # 4) 运行六节点规划控制面（plan/supervise/execute_batch/replan/
        #    request_human_input/finalize）；Worker 只读，finalize 只产出报告或派单建议。
        result = await self.planning_runtime.run(incident)
        proposal = result.proposal
        if proposal is not None and proposal.work_order_id:
            # 4a) 规划只产出建议。统一入口把建议交回前端，由管理员显式确认后调用
            #     Java 业务接口；Java 再负责鉴权、Outbox、RabbitMQ 和最终竞争控制。
            return AssistantExecution(
                route_type=RouteType.INCIDENT_INVESTIGATION,
                trace_id=trace_id,
                outcome=AssistantOutcome.NEEDS_APPROVAL,
                message=f"调查建议对工单 {proposal.work_order_id} 发起自动派单，请管理员确认。",
                route_reason_code=decision.reason_code,
                execution_mode="multi_agent_planning",
                planning=result,
                next_action=NextAction(
                    type="trigger_java_dispatch",
                    continuation_id=proposal.work_order_id,
                    input_schema={
                        "required": ["work_order_id", "idempotency_key"],
                        "properties": {
                            "work_order_id": {"const": proposal.work_order_id}
                        },
                    },
                    resume_endpoint=(
                        f"/deviceMaintain/{proposal.work_order_id}/auto-dispatch"
                    ),
                ),
            )
        # 4b) 无派单建议（仅报告或等待人工输入）：按规划状态映射 outcome。
        outcome = {
            "completed": AssistantOutcome.COMPLETED,
            "failed": AssistantOutcome.FAILED,
            "awaiting_human": AssistantOutcome.NEEDS_INPUT,
        }.get(result.status, AssistantOutcome.FAILED)
        return AssistantExecution(
            route_type=RouteType.INCIDENT_INVESTIGATION,
            trace_id=trace_id,
            outcome=outcome,
            message=result.report,
            route_reason_code=decision.reason_code,
            execution_mode="multi_agent_planning",
            planning=result,
            # 等待人工输入时附上续接入口：允许 retry 或 cancel，并携带补充信息。
            next_action=(
                NextAction(
                    type="provide_planning_input",
                    continuation_id=result.thread_id,
                    input_schema={
                        "required": ["action", "information"],
                        "properties": {
                            "action": {"enum": ["retry", "cancel"]},
                            "information": {"type": "string"},
                        },
                    },
                    resume_endpoint=f"/v1/planning/{result.thread_id}/resume",
                )
                if result.status == "awaiting_human" and result.thread_id
                else None
            ),
        )

    def _business_input_required(
        self,
        *,
        route_type: RouteType,
        message: str,
        trace_id: str,
        missing_fields: list[str],
        prompt: str,
        namespace: ConversationNamespace | None,
    ) -> AssistantExecution:
        if self.conversation and namespace:
            self.conversation.save_pending(
                namespace,
                PendingTurn(
                    original_message=message,
                    missing_fields=missing_fields,
                    trace_id=trace_id,
                    route_type=route_type.value,
                ),
            )
        return AssistantExecution(
            route_type=route_type,
            trace_id=trace_id,
            outcome=AssistantOutcome.NEEDS_INPUT,
            message=prompt,
            execution_mode="clarification",
            missing_fields=missing_fields,
            next_action=(
                NextAction(
                    type="provide_fields",
                    continuation_id=namespace.thread_id,
                    input_schema={"required": missing_fields},
                    resume_endpoint="/v1/assistant/execute",
                )
                if namespace
                else None
            ),
        )

    @staticmethod
    def _namespace(
        tenant_id: str, user_id: str | None, thread_id: str | None
    ) -> ConversationNamespace | None:
        if not user_id or not thread_id:
            return None
        return ConversationNamespace(
            tenant_id=tenant_id, user_id=user_id, thread_id=thread_id
        )

    def _setting(self, name: str, default: int) -> int:
        return int(getattr(self.settings, name, default)) if self.settings else default

    @staticmethod
    def _use_single_agent(message: str, decision) -> bool:
        """无关联工单且未命中复杂度信号时使用低成本只读调查。"""
        if decision.extracted_entities.work_order_id:
            return False
        complex_signals = (
            "多设备",
            "批量",
            "大面积",
            "停机",
            "生产线",
            "影响范围",
            "安全风险",
            "资源规划",
            "sla",
            "跨区域",
            "派单建议",
            "应急",
            "升级",
        )
        normalized = message.lower()
        return not any(signal in normalized for signal in complex_signals)

    async def _route(self, message: str, **kwargs):
        """兼容只实现确定性 route 的测试/离线 Router，同时生产使用异步 LLM 兜底。"""
        async_route = getattr(self.request_router, "route_async", None)
        if async_route is not None:
            return await async_route(message, **kwargs)
        return self.request_router.route(message, **kwargs)
