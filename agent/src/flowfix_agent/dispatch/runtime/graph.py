from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from flowfix_agent.dispatch.application.service import DispatchDecisionService
from flowfix_agent.dispatch.domain.models import (
    DispatchDecision,
    DispatchOutcome,
    DispatchRequest,
    WorkerSnapshot,
    WorkOrderSnapshot,
)
from flowfix_agent.dispatch.runtime.errors import ApprovalValidationError
from flowfix_agent.dispatch.runtime.middleware import DispatchToolGateway
from flowfix_agent.dispatch.runtime.models import (
    ApprovalDecision,
    AssignmentCommand,
    AssignmentOutcome,
    AssignmentOutcomeStatus,
    AssignmentReceipt,
    AssignmentReceiptStatus,
    DispatchRuntimeInput,
    RequestContext,
    RuntimeResult,
    RuntimeStatus,
)
from flowfix_agent.dispatch.skills.manifest import DispatchSkill


# 定义 LangGraph 节点之间持久化传递的派单运行时状态。
class DispatchGraphState(TypedDict, total=False):
    dispatch_id: str
    event_id: str
    tenant_id: str
    work_order_id: str
    request: dict[str, Any]
    context: dict[str, Any]
    skill: dict[str, Any]
    work_order: dict[str, Any]
    workers: list[dict[str, Any]]
    decision: dict[str, Any]
    approval: dict[str, Any]
    assignment_command: dict[str, Any]
    assignment_receipt: dict[str, Any]
    assignment_outcome: dict[str, Any]
    audit_result: dict[str, Any]
    requires_approval: bool
    runtime_status: str
    errors: list[str]


# 编排 Skill 冻结、快照读取、决策、审批、写入、核验和审计状态图。
class DispatchAgentRuntime:
    """固定主图：冻结 -> 决策 -> 审批 -> 写入 -> 核验 -> 审计。"""

    # 注入决策服务和受控工具网关，并使用检查点编译状态图。
    def __init__(
        self,
        decision_service: DispatchDecisionService,
        tools: DispatchToolGateway,
        checkpointer: BaseCheckpointSaver | None = None,
    ) -> None:
        self.decision_service = decision_service
        self.tools = tools
        self.checkpointer = checkpointer or InMemorySaver()
        self.graph = self._build_graph().compile(checkpointer=self.checkpointer)

    # 以新的派单输入初始化线程状态并执行到终点或人工中断点。
    async def start(self, runtime_input: DispatchRuntimeInput) -> RuntimeResult:
        thread_id = self._thread_id(
            runtime_input.request.tenant_id, runtime_input.request.dispatch_id
        )
        initial: DispatchGraphState = {
            "dispatch_id": runtime_input.request.dispatch_id,
            "event_id": runtime_input.request.event_id,
            "tenant_id": runtime_input.request.tenant_id,
            "work_order_id": runtime_input.work_order_id,
            "request": runtime_input.request.model_dump(mode="json"),
            "context": runtime_input.context.model_dump(mode="json"),
            "requires_approval": runtime_input.requires_approval,
            "runtime_status": RuntimeStatus.RECEIVED.value,
            "errors": [],
        }
        output = await self.graph.ainvoke(initial, self._config(thread_id))
        return await self._result(thread_id, output)

    # 使用人工审批结果恢复指定线程并继续执行状态图。
    async def resume(
        self,
        thread_id: str,
        approval: ApprovalDecision,
        *,
        tenant_id: str | None = None,
    ) -> RuntimeResult:
        state = await self._owned_state(thread_id, tenant_id)
        context = RequestContext.model_validate(state["context"])
        if context.approval_expires_at and datetime.now(UTC) >= context.approval_expires_at:
            raise ApprovalValidationError("dispatch approval expired")
        renewed = context.model_copy(
            update={
                "deadline": datetime.now(UTC)
                + timedelta(seconds=context.execution_timeout_seconds)
            }
        )
        output = await self.graph.ainvoke(
            Command(
                resume=approval.model_dump(mode="json"),
                update={"context": renewed.model_dump(mode="json")},
            ),
            self._config(thread_id),
        )
        return await self._result(thread_id, output)

    # 从最近检查点重试因依赖故障停止的派单线程。
    async def retry(
        self, thread_id: str, *, tenant_id: str | None = None
    ) -> RuntimeResult:
        state = await self._owned_state(thread_id, tenant_id)
        context = RequestContext.model_validate(state["context"])
        renewed = context.model_copy(
            update={
                "deadline": datetime.now(UTC)
                + timedelta(seconds=context.execution_timeout_seconds)
            }
        )
        output = await self.graph.ainvoke(
            Command(update={"context": renewed.model_dump(mode="json")}),
            self._config(thread_id),
        )
        return await self._result(thread_id, output)

    # 按检查点历史返回指定线程的全部状态快照。
    async def state_history(
        self, thread_id: str, *, tenant_id: str | None = None
    ) -> list[dict[str, Any]]:
        await self._owned_state(thread_id, tenant_id)
        return [
            dict(snapshot.values)
            async for snapshot in self.graph.aget_state_history(self._config(thread_id))
        ]

    # 读取线程最新检查点并返回稳定运行结果。
    async def status(
        self, thread_id: str, *, tenant_id: str | None = None
    ) -> RuntimeResult:
        state = await self._owned_state(thread_id, tenant_id)
        return await self._result(thread_id, state)

    async def _owned_state(
        self, thread_id: str, tenant_id: str | None
    ) -> dict[str, Any]:
        snapshot = await self.graph.aget_state(self._config(thread_id))
        state = dict(snapshot.values)
        if not state:
            raise ApprovalValidationError(f"dispatch thread not found: {thread_id}")
        if tenant_id is not None and state.get("tenant_id") != tenant_id:
            raise ApprovalValidationError("dispatch thread belongs to another tenant")
        return state

    # 创建固定节点、条件路由和终止边组成的派单状态图。
    def _build_graph(self) -> StateGraph:
        builder = StateGraph(DispatchGraphState)
        builder.add_node("freeze_skill", self._freeze_skill)
        builder.add_node("load_snapshot", self._load_snapshot)
        builder.add_node("decide", self._decide)
        builder.add_node("mark_approval", self._mark_approval)
        builder.add_node("human_approval", self._human_approval)
        builder.add_node("execute", self._execute)
        builder.add_node("verify", self._verify)
        builder.add_node("audit", self._audit)
        builder.add_edge(START, "freeze_skill")
        builder.add_edge("freeze_skill", "load_snapshot")
        builder.add_edge("load_snapshot", "decide")
        builder.add_conditional_edges(
            "decide",
            self._route_decision,
            {"execute": "execute", "approval": "mark_approval", "audit": "audit"},
        )
        builder.add_edge("mark_approval", "human_approval")
        builder.add_conditional_edges(
            "human_approval",
            self._route_approval,
            {"execute": "execute", "audit": "audit"},
        )
        builder.add_conditional_edges(
            "execute",
            self._route_receipt,
            {"verify": "verify", "audit": "audit"},
        )
        builder.add_edge("verify", "audit")
        builder.add_edge("audit", END)
        return builder

    # 深拷贝当前激活 Skill，使后续恢复不受策略切换影响。
    async def _freeze_skill(self, state: DispatchGraphState) -> dict[str, Any]:
        skill = self.decision_service.registry.get_active().model_copy(deep=True)
        return {"skill": skill.model_dump(mode="json")}

    # 通过受控工具读取并冻结工单及工作人员快照。
    async def _load_snapshot(self, state: DispatchGraphState) -> dict[str, Any]:
        context = RequestContext.model_validate(state["context"])
        skill = DispatchSkill.model_validate(state["skill"])
        order = await self.tools.get_work_order_snapshot(
            state["work_order_id"], context, skill
        )
        workers = await self.tools.list_eligible_workers(order, context, skill)
        return {
            "work_order": order.model_dump(mode="json"),
            "workers": [worker.model_dump(mode="json") for worker in workers],
            "runtime_status": RuntimeStatus.SNAPSHOT_FROZEN.value,
        }

    # 使用冻结输入和 Skill 生成决策，并标记拒绝或无候选分支。
    async def _decide(self, state: DispatchGraphState) -> dict[str, Any]:
        request = DispatchRequest.model_validate(state["request"])
        order = WorkOrderSnapshot.model_validate(state["work_order"])
        workers = [WorkerSnapshot.model_validate(item) for item in state["workers"]]
        skill = DispatchSkill.model_validate(state["skill"])
        prepared = self.decision_service.prepare(request, order, workers, skill=skill)
        decision = await self.decision_service.decide_prepared(prepared)
        status = RuntimeStatus.DECISION_READY
        errors = list(state.get("errors", []))
        if decision.outcome == DispatchOutcome.REJECTED:
            status = RuntimeStatus.DENIED
            errors.append("dispatch_decision_rejected")
        elif decision.outcome == DispatchOutcome.MANUAL and not decision.candidates:
            status = RuntimeStatus.DENIED
            errors.append("manual_review_has_no_eligible_candidate")
        return {
            "decision": decision.model_dump(mode="json"),
            "runtime_status": status.value,
            "errors": errors,
        }

    # 在进入人工节点前把运行时状态标记为等待审批。
    async def _mark_approval(self, state: DispatchGraphState) -> dict[str, Any]:
        return {"runtime_status": RuntimeStatus.AWAITING_APPROVAL.value}

    # 中断图等待人工结论，并校验批准人员属于冻结候选集。
    async def _human_approval(self, state: DispatchGraphState) -> dict[str, Any]:
        # 从图状态还原冻结的决策结果，作为展示给人工审批者的唯一依据。
        decision = DispatchDecision.model_validate(state["decision"])
        # 组装待人工确认的载荷：只暴露派单标识、风险等级、决策理由与候选人员，
        # 不暴露 Skill 等内部结构，避免审批界面感知实现细节。
        payload = {
            "dispatch_id": decision.dispatch_id,
            "event_id": decision.event_id,
            "risk_level": decision.risk_level.value,
            "reasons": decision.reasons,
            "candidates": [item.model_dump(mode="json") for item in decision.candidates],
        }
        # interrupt 挂起图执行并把载荷交给审批人，恢复时返回其结论；
        # 每次执行在此处暂停，恢复通过 resume() 继续，因此属于 HITL 安全区。
        approval = ApprovalDecision.model_validate(interrupt(payload))
        # 把冻结候选集转成集合，用于校验被批准人员确实在候选名单内。
        candidates = {candidate.worker_id for candidate in decision.candidates}
        # 安全不变量：批准只能落在冻结候选集内，防止绕过决策外部指定派单人。
        if approval.approved and approval.worker_id not in candidates:
            raise ApprovalValidationError(
                f"approved worker is not an eligible candidate: {approval.worker_id}"
            )
        # 把人工结论写回状态并映射运行时状态：批准/拒绝分别推进到对应终态。
        return {
            "approval": approval.model_dump(mode="json"),
            "runtime_status": (
                RuntimeStatus.APPROVED.value
                if approval.approved
                else RuntimeStatus.DENIED.value
            ),
        }

    # 构造带期望版本的幂等派单命令并通过工具网关执行。
    async def _execute(self, state: DispatchGraphState) -> dict[str, Any]:
        # 1) 从状态还原决策、上下文与所选 Skill；审批结论仅在走 HITL 审批后有。
        decision = DispatchDecision.model_validate(state["decision"])
        context = RequestContext.model_validate(state["context"])
        skill = DispatchSkill.model_validate(state["skill"])
        approval = (
            ApprovalDecision.model_validate(state["approval"])
            if state.get("approval")
            else None
        )
        # 2) 确定派单对象：经人工审批时用审批指定的工人，否则用决策预选的工人；
        #    两者都缺失则无法执行，属非法图状态，直接失败。
        worker_id = approval.worker_id if approval else decision.selected_worker_id
        if not worker_id:
            raise ApprovalValidationError("execution requires a selected worker")
        # 3) 组装幂等派单命令：expected_version 携带决策时读到的工单版本，
        #    idempotency_key 由租户/事件/工单/版本唯一决定，供 Java 侧防重复派单。
        command = AssignmentCommand(
            tenant_id=decision.tenant_id,
            event_id=decision.event_id,
            dispatch_id=decision.dispatch_id,
            work_order_id=decision.work_order_id,
            worker_id=worker_id,
            expected_version=decision.work_order_version,
            idempotency_key=(
                f"assignment:{decision.tenant_id}:{decision.event_id}:"
                f"{decision.work_order_id}:v{decision.work_order_version}"
            ),
        )
        # 4) 经工具网关执行派单；真实写入由 Java 完成，这里只拿受理回执。
        receipt = await self.tools.create_assignment(command, context, skill)
        # 5) 只有被受理（或已应用=幂等命中）才算推进成功，其余一律失败并记录原因。
        errors = list(state.get("errors", []))
        runtime_status = RuntimeStatus.EXECUTING
        if receipt.status not in {
            AssignmentReceiptStatus.ACCEPTED,
            AssignmentReceiptStatus.ALREADY_APPLIED,
        }:
            runtime_status = RuntimeStatus.FAILED
            errors.append(f"assignment_receipt:{receipt.status}")
        # 6) 写回命令、回执与运行时状态，交由下一节点校验或审计。
        return {
            "assignment_command": command.model_dump(mode="json"),
            "assignment_receipt": receipt.model_dump(mode="json"),
            "runtime_status": runtime_status.value,
            "errors": errors,
        }

    # 查询派单最终结果并核对人员和工单版本是否符合命令。
    async def _verify(self, state: DispatchGraphState) -> dict[str, Any]:
        command = AssignmentCommand.model_validate(state["assignment_command"])
        context = RequestContext.model_validate(state["context"])
        skill = DispatchSkill.model_validate(state["skill"])
        outcome = await self.tools.get_assignment_outcome(
            command.dispatch_id, context, skill
        )
        valid = (
            outcome.status == AssignmentOutcomeStatus.ASSIGNED
            and outcome.assigned_worker_id == command.worker_id
            and outcome.work_order_version is not None
            and outcome.work_order_version > command.expected_version
        )
        errors = list(state.get("errors", []))
        if not valid:
            errors.append(f"assignment_outcome_not_verified:{outcome.status}")
        return {
            "assignment_outcome": outcome.model_dump(mode="json"),
            "runtime_status": (
                RuntimeStatus.VERIFIED.value if valid else RuntimeStatus.FAILED.value
            ),
            "errors": errors,
        }

    # 汇总决策、审批、回执、结果和错误并幂等发布审计事件。
    async def _audit(self, state: DispatchGraphState) -> dict[str, Any]:
        # 1) 还原执行上下文与所选 Skill，用于审计发布的鉴权与路由。
        context = RequestContext.model_validate(state["context"])
        skill = DispatchSkill.model_validate(state["skill"])
        # 2) 汇总本线程完整执行证据：状态、决策、审批结论、派单回执、终态结果与错误。
        #    快照形式落库，保证审计面不依赖后续状态变化。
        payload = {
            "runtime_status": state["runtime_status"],
            "decision": state.get("decision"),
            "approval": state.get("approval"),
            "assignment_receipt": state.get("assignment_receipt"),
            "assignment_outcome": state.get("assignment_outcome"),
            "errors": state.get("errors", []),
        }
        # 3) 经工具网关发布派单审计（真实落库由 Java 完成）。
        result = await self.tools.publish_dispatch_audit(
            state["dispatch_id"], payload, context, skill
        )
        # 4) 审计本身不改变终态结果；仅当已 VERIFIED 时推进为 AUDITED 终态。
        updates: dict[str, Any] = {"audit_result": result.model_dump(mode="json")}
        if state["runtime_status"] == RuntimeStatus.VERIFIED:
            updates["runtime_status"] = RuntimeStatus.AUDITED.value
        return updates

    # 根据领域决策选择直接执行、进入审批或仅审计。
    @staticmethod
    def _route_decision(state: DispatchGraphState) -> str:
        decision = DispatchDecision.model_validate(state["decision"])
        if decision.outcome == DispatchOutcome.ASSIGN:
            # 强制审批开关（调查链建议转交）下，即使可自动派单也进入人工审批。
            if state.get("requires_approval"):
                return "approval"
            return "execute"
        if decision.outcome == DispatchOutcome.MANUAL and decision.candidates:
            return "approval"
        return "audit"

    # 根据人工审批结论选择执行派单或结束并审计。
    @staticmethod
    def _route_approval(state: DispatchGraphState) -> str:
        approval = ApprovalDecision.model_validate(state["approval"])
        return "execute" if approval.approved else "audit"

    # 根据写入回执选择核验最终结果或直接进入审计。
    @staticmethod
    def _route_receipt(state: DispatchGraphState) -> str:
        receipt = AssignmentReceipt.model_validate(state["assignment_receipt"])
        if receipt.status in {
            AssignmentReceiptStatus.ACCEPTED,
            AssignmentReceiptStatus.ALREADY_APPLIED,
        }:
            return "verify"
        return "audit"

    # 合并最新检查点与本次输出，构造对调用方稳定的运行结果。
    async def _result(
        self, thread_id: str, output: dict[str, Any]
    ) -> RuntimeResult:
        snapshot = await self.graph.aget_state(self._config(thread_id))
        state = dict(snapshot.values or output)
        interrupted = bool(getattr(snapshot, "interrupts", ())) or "__interrupt__" in output
        outcome = (
            AssignmentOutcome.model_validate(state["assignment_outcome"])
            if state.get("assignment_outcome")
            else None
        )
        approval = (
            ApprovalDecision.model_validate(state["approval"])
            if state.get("approval")
            else None
        )
        return RuntimeResult(
            thread_id=thread_id,
            status=RuntimeStatus(state["runtime_status"]),
            interrupted=interrupted,
            decision=state.get("decision"),
            assignment_outcome=outcome,
            approval=approval,
            errors=state.get("errors", []),
            approval_expires_at=(
                RequestContext.model_validate(state["context"]).approval_expires_at
                if state.get("context")
                else None
            ),
            state=state,
        )

    # 生成 LangGraph 按派单线程隔离检查点所需的配置。
    @staticmethod
    def _config(thread_id: str) -> dict[str, dict[str, str]]:
        return {"configurable": {"thread_id": thread_id}}

    @staticmethod
    def _thread_id(tenant_id: str, dispatch_id: str) -> str:
        return f"dispatch:{tenant_id}:{dispatch_id}"
