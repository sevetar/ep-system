from __future__ import annotations

from collections import Counter
from typing import Any

from flowfix_agent.core.errors import DependencyUnavailableError
from flowfix_agent.dispatch.domain.models import WorkerSnapshot, WorkOrderSnapshot, WorkOrderStatus
from flowfix_agent.dispatch.runtime.models import (
    AssignmentCommand,
    AssignmentOutcome,
    AssignmentOutcomeStatus,
    AssignmentReceipt,
    AssignmentReceiptStatus,
    AuditPublishResult,
    PolicyEvidence,
    RequestContext,
    ToolName,
)


# 模拟 Java 派单工具合同，并记录调用次数、失败和业务副作用。
class FakeDispatchToolAdapter:
    """M4 可控 Fake：模拟 Java 合同并暴露调用/副作用计数。"""

    # 深拷贝初始快照并初始化幂等结果、审计和计数容器。
    def __init__(
        self,
        work_orders: list[WorkOrderSnapshot],
        workers: list[WorkerSnapshot],
        policies: list[PolicyEvidence] | None = None,
    ) -> None:
        self.work_orders = {
            item.work_order_id: item.model_copy(deep=True) for item in work_orders
        }
        self.workers = [item.model_copy(deep=True) for item in workers]
        self.policies = list(policies or [])
        self.call_counts: Counter[str] = Counter()
        self.side_effect_counts: Counter[str] = Counter()
        self.failures_before_success: Counter[str] = Counter()
        self.assignments: dict[str, AssignmentOutcome] = {}
        self.receipts: dict[str, AssignmentReceipt] = {}
        self.commands: dict[str, AssignmentCommand] = {}
        self.audits: dict[str, dict[str, Any]] = {}

    # 配置指定工具在后续若干次调用中模拟依赖故障。
    def fail_next(self, tool_name: ToolName, times: int = 1) -> None:
        self.failures_before_success[tool_name.value] += times

    # 按工单标识和租户上下文返回隔离的工单快照。
    async def get_work_order_snapshot(
        self, work_order_id: str, context: RequestContext
    ) -> WorkOrderSnapshot:
        self._before(ToolName.GET_WORK_ORDER_SNAPSHOT)
        order = self.work_orders.get(work_order_id)
        if order is None or order.tenant_id != context.tenant_id:
            raise KeyError(f"work_order_not_found:{work_order_id}")
        return order.model_copy(deep=True)

    # 返回与请求租户一致的工作人员快照供领域层继续筛选。
    async def list_eligible_workers(
        self, work_order: WorkOrderSnapshot, context: RequestContext
    ) -> list[WorkerSnapshot]:
        self._before(ToolName.LIST_ELIGIBLE_WORKERS)
        return [
            worker.model_copy(deep=True)
            for worker in self.workers
            if worker.tenant_id == context.tenant_id
        ]

    # 批量返回请求租户内指定工作人员的当前负载。
    async def get_worker_loads(
        self, worker_ids: list[str], context: RequestContext
    ) -> dict[str, int]:
        self._before(ToolName.GET_WORKER_LOADS)
        requested = set(worker_ids)
        return {
            worker.worker_id: worker.current_load
            for worker in self.workers
            if worker.tenant_id == context.tenant_id and worker.worker_id in requested
        }

    # 在预置策略证据中执行不区分大小写的文本匹配。
    async def search_dispatch_policy(
        self, query: str, context: RequestContext
    ) -> list[PolicyEvidence]:
        self._before(ToolName.SEARCH_DISPATCH_POLICY)
        lowered = query.lower()
        return [item for item in self.policies if lowered in item.content.lower()]

    # 按幂等键和期望版本模拟创建派单并保存可核验结果。
    async def create_assignment(
        self, command: AssignmentCommand, context: RequestContext
    ) -> AssignmentReceipt:
        self._before(ToolName.CREATE_ASSIGNMENT)
        existing = self.receipts.get(command.idempotency_key)
        if existing:
            original = self.commands[command.idempotency_key]
            if original != command:
                return AssignmentReceipt(
                    status=AssignmentReceiptStatus.REJECTED,
                    idempotency_key=command.idempotency_key,
                    work_order_id=command.work_order_id,
                    observed_version=existing.observed_version,
                    message="idempotency_key_reused_with_different_command",
                )
            return existing.model_copy(
                update={"status": AssignmentReceiptStatus.ALREADY_APPLIED}, deep=True
            )

        order = self.work_orders.get(command.work_order_id)
        if order is None or order.tenant_id != context.tenant_id:
            return AssignmentReceipt(
                status=AssignmentReceiptStatus.REJECTED,
                idempotency_key=command.idempotency_key,
                work_order_id=command.work_order_id,
                observed_version=0,
                message="work_order_not_found",
            )
        if order.version != command.expected_version:
            return AssignmentReceipt(
                status=AssignmentReceiptStatus.VERSION_CONFLICT,
                idempotency_key=command.idempotency_key,
                work_order_id=command.work_order_id,
                observed_version=order.version,
                message="expected_version_mismatch",
            )

        updated = order.model_copy(
            update={
                "status": WorkOrderStatus.ASSIGNED,
                "assigned_worker_id": command.worker_id,
                "version": order.version + 1,
            },
            deep=True,
        )
        self.work_orders[order.work_order_id] = updated
        receipt = AssignmentReceipt(
            status=AssignmentReceiptStatus.ACCEPTED,
            idempotency_key=command.idempotency_key,
            work_order_id=order.work_order_id,
            worker_id=command.worker_id,
            observed_version=updated.version,
            message="assignment_accepted",
        )
        outcome = AssignmentOutcome(
            status=AssignmentOutcomeStatus.ASSIGNED,
            idempotency_key=command.idempotency_key,
            work_order_id=order.work_order_id,
            assigned_worker_id=command.worker_id,
            work_order_version=updated.version,
            message="assignment_verified",
        )
        self.receipts[command.idempotency_key] = receipt
        self.commands[command.idempotency_key] = command.model_copy(deep=True)
        self.assignments[command.dispatch_id] = outcome
        self.side_effect_counts[ToolName.CREATE_ASSIGNMENT.value] += 1
        return receipt.model_copy(deep=True)

    # 按派单标识读取已保存的派单执行结果。
    async def get_assignment_outcome(
        self, dispatch_id: str, context: RequestContext
    ) -> AssignmentOutcome:
        self._before(ToolName.GET_ASSIGNMENT_OUTCOME)
        outcome = self.assignments.get(dispatch_id)
        if outcome:
            return outcome.model_copy(deep=True)
        return AssignmentOutcome(
            status=AssignmentOutcomeStatus.NOT_FOUND,
            idempotency_key="unknown",
            work_order_id="unknown",
            work_order_version=0,
            message="assignment_not_found",
        )

    # 幂等发布派单审计载荷并记录实际副作用次数。
    async def publish_dispatch_audit(
        self, dispatch_id: str, payload: dict[str, Any], context: RequestContext
    ) -> AuditPublishResult:
        self._before(ToolName.PUBLISH_DISPATCH_AUDIT)
        if dispatch_id in self.audits:
            return AuditPublishResult(status="already_published", dispatch_id=dispatch_id)
        self.audits[dispatch_id] = dict(payload)
        self.side_effect_counts[ToolName.PUBLISH_DISPATCH_AUDIT.value] += 1
        return AuditPublishResult(status="published", dispatch_id=dispatch_id)

    # 记录工具调用，并在配置故障时于业务处理前抛出异常。
    def _before(self, tool_name: ToolName) -> None:
        self.call_counts[tool_name.value] += 1
        if self.failures_before_success[tool_name.value] > 0:
            self.failures_before_success[tool_name.value] -= 1
            raise DependencyUnavailableError(f"fake_dependency_failure:{tool_name.value}")
