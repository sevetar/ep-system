from __future__ import annotations

from datetime import UTC, datetime, timedelta

from flowfix_agent.core.errors import FlowFixError
from flowfix_agent.dispatch.domain.models import DispatchRequest
from flowfix_agent.dispatch.runtime.graph import DispatchAgentRuntime
from flowfix_agent.dispatch.runtime.models import (
    ApprovalDecision,
    DispatchRuntimeInput,
    RequestContext,
    RuntimeResult,
)
from flowfix_agent.planning.completion import WritePolicy
from flowfix_agent.planning.models import DispatchProposal

# 派单建议转交派单链路所需的权限集合：读快照、写派单与发布审计。
_TRANSFER_PERMISSIONS = ["dispatch:read", "dispatch:write", "dispatch:audit"]


# 表示派单建议未通过只读校验或血缘校验，拒绝转交派单链路。
class ProposalTransferError(FlowFixError):
    pass


# 调查链 → 派单链路边界：校验只读派单建议并强制经人工审批后启动派单运行时。
class ProposalDispatchBridge:
    """WritePolicy 防线后的唯一转交入口：非合规建议直接拒绝，不触碰 Java。"""

    # 注入派单运行时，并分别设置自动执行时限与人工审批有效期。
    def __init__(
        self,
        runtime: DispatchAgentRuntime,
        *,
        execution_timeout_seconds: int = 60,
        approval_ttl_seconds: int = 3600,
        timeout_seconds: float | None = None,
    ) -> None:
        self.runtime = runtime
        self.execution_timeout_seconds = int(timeout_seconds or execution_timeout_seconds)
        self.approval_ttl_seconds = approval_ttl_seconds

    # 校验派单建议合规，组装带强制审批开关的派单运行时输入。
    def to_runtime_input(
        self,
        proposal: DispatchProposal,
        *,
        tenant_id: str,
        context: RequestContext | None = None,
    ) -> DispatchRuntimeInput:
        violations = WritePolicy.validate_proposal(proposal)
        if violations:
            raise ProposalTransferError(f"派单建议未通过只读校验，拒绝转交: {violations}")
        if not proposal.requires_approval:
            raise ProposalTransferError("派单建议必须要求人工审批")
        if not tenant_id:
            raise ProposalTransferError("派单转交缺少租户上下文")
        ctx = context or RequestContext(
            trace_id=f"{proposal.proposal_id}:transfer",
            tenant_id=tenant_id,
            event_id=proposal.proposal_id,
            permissions=list(_TRANSFER_PERMISSIONS),
            deadline=datetime.now(UTC)
            + timedelta(seconds=self.execution_timeout_seconds),
            approval_expires_at=datetime.now(UTC)
            + timedelta(seconds=self.approval_ttl_seconds),
            execution_timeout_seconds=self.execution_timeout_seconds,
        )
        # 血缘校验前置失败：事件与租户不一致的上下文不得进入派单运行时。
        if ctx.event_id != proposal.proposal_id:
            raise ProposalTransferError(
                f"context event_id 与提案不一致: {ctx.event_id} != {proposal.proposal_id}"
            )
        if ctx.tenant_id != tenant_id:
            raise ProposalTransferError(
                f"context tenant_id 与转交租户不一致: {ctx.tenant_id} != {tenant_id}"
            )
        return DispatchRuntimeInput(
            request=DispatchRequest(
                dispatch_id=proposal.proposal_id,
                event_id=proposal.proposal_id,
                tenant_id=tenant_id,
                # 用提案自身的生成时间作为请求时间，保证重复转交的输入指纹稳定。
                requested_at=proposal.created_at,
            ),
            work_order_id=proposal.work_order_id,
            context=ctx,
            # 调查链建议永远要求人工审批，写入安全区由 Dispatch 链路统一保障。
            requires_approval=True,
        )

    # 将合规派单建议转交派单链路并执行到终点或人工中断点。
    async def transfer(
        self,
        proposal: DispatchProposal,
        *,
        tenant_id: str,
        context: RequestContext | None = None,
    ) -> RuntimeResult:
        runtime_input = self.to_runtime_input(
            proposal, tenant_id=tenant_id, context=context
        )
        return await self.runtime.start(runtime_input)

    # 人工批准已冻结候选集中的工作人员并继续执行派单。
    async def approve(
        self,
        thread_id: str,
        *,
        reviewer_id: str,
        worker_id: str,
        reason: str,
    ) -> RuntimeResult:
        approval = ApprovalDecision(
            approved=True,
            reviewer_id=reviewer_id,
            worker_id=worker_id,
            reason=reason,
        )
        return await self.runtime.resume(thread_id, approval)

    # 人工拒绝派单，转审计结束，不执行任何写入。
    async def deny(
        self,
        thread_id: str,
        *,
        reviewer_id: str,
        reason: str,
    ) -> RuntimeResult:
        approval = ApprovalDecision(
            approved=False,
            reviewer_id=reviewer_id,
            reason=reason,
        )
        return await self.runtime.resume(thread_id, approval)
