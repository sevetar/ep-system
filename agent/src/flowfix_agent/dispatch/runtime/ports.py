from __future__ import annotations

from typing import Any, Protocol

from flowfix_agent.dispatch.domain.models import WorkerSnapshot, WorkOrderSnapshot
from flowfix_agent.dispatch.runtime.models import (
    ApprovalDecision,
    AssignmentCommand,
    AssignmentOutcome,
    AssignmentReceipt,
    AuditPublishResult,
    DispatchRuntimeInput,
    PolicyEvidence,
    RequestContext,
    RuntimeResult,
)


# 定义运行时访问工单、人员、策略、派单和审计系统的工具合同。
class DispatchToolPort(Protocol):
    # 按工单标识读取租户范围内的不可变工单快照。
    async def get_work_order_snapshot(
        self, work_order_id: str, context: RequestContext
    ) -> WorkOrderSnapshot: ...

    # 读取可供领域层继续筛选的工作人员快照。
    async def list_eligible_workers(
        self, work_order: WorkOrderSnapshot, context: RequestContext
    ) -> list[WorkerSnapshot]: ...

    # 批量读取指定工作人员的当前负载。
    async def get_worker_loads(
        self, worker_ids: list[str], context: RequestContext
    ) -> dict[str, int]: ...

    # 根据查询文本检索只读派单策略证据。
    async def search_dispatch_policy(
        self, query: str, context: RequestContext
    ) -> list[PolicyEvidence]: ...

    # 向业务系统提交带幂等键和期望版本的派单命令。
    async def create_assignment(
        self, command: AssignmentCommand, context: RequestContext
    ) -> AssignmentReceipt: ...

    # 按派单标识查询派单命令的最终业务结果。
    async def get_assignment_outcome(
        self, dispatch_id: str, context: RequestContext
    ) -> AssignmentOutcome: ...

    # 幂等发布一次派单运行时审计记录。
    async def publish_dispatch_audit(
        self, dispatch_id: str, payload: dict[str, Any], context: RequestContext
    ) -> AuditPublishResult: ...


# 派单运行时对上层（统一入口/API）暴露的编排合同：启动、恢复、查询与重试。
class DispatchRuntimePort(Protocol):
    # 以新的派单输入初始化线程状态并执行到终点或人工中断点。
    async def start(self, runtime_input: DispatchRuntimeInput) -> RuntimeResult: ...

    # 使用人工审批结果恢复指定线程并继续执行状态图。
    async def resume(
        self,
        thread_id: str,
        approval: ApprovalDecision,
        *,
        tenant_id: str | None = None,
    ) -> RuntimeResult: ...

    # 从最近检查点重试因依赖故障停止的派单线程。
    async def retry(
        self, thread_id: str, *, tenant_id: str | None = None
    ) -> RuntimeResult: ...

    # 读取线程最新检查点并返回稳定运行结果。
    async def status(
        self, thread_id: str, *, tenant_id: str | None = None
    ) -> RuntimeResult: ...

    # 按检查点历史返回指定线程的全部状态快照。
    async def state_history(
        self, thread_id: str, *, tenant_id: str | None = None
    ) -> list[dict[str, Any]]: ...
