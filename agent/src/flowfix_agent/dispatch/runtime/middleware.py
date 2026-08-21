from __future__ import annotations

import asyncio
import time
from collections import Counter, deque
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, TypeVar

from pydantic import BaseModel

from flowfix_agent.core.errors import DependencyUnavailableError
from flowfix_agent.dispatch.domain.models import WorkerSnapshot, WorkOrderSnapshot
from flowfix_agent.dispatch.runtime.errors import (
    ToolAccessDeniedError,
    ToolCircuitOpenError,
    ToolContractError,
    ToolDeadlineExceededError,
    ToolRateLimitError,
)
from flowfix_agent.dispatch.runtime.models import (
    AssignmentCommand,
    AssignmentOutcome,
    AssignmentReceipt,
    AuditPublishResult,
    PolicyEvidence,
    RequestContext,
    ToolAuditEvent,
    ToolName,
)
from flowfix_agent.dispatch.runtime.ports import DispatchToolPort
from flowfix_agent.dispatch.skills.manifest import DispatchSkill

T = TypeVar("T")
SENSITIVE_KEYS = {"authorization", "password", "secret", "token", "api_key"}
READ_PERMISSION = "dispatch:read"
WRITE_PERMISSION = "dispatch:write"
AUDIT_PERMISSION = "dispatch:audit"


# 统一执行工具授权、合同校验、预算、超时、重试、熔断和审计。
class DispatchToolGateway:
    """系统 allowlist、Skill policy 和请求权限共同约束 Tool 调用。"""

    # 注入工具适配器并初始化系统白名单、可靠性参数和审计状态。
    def __init__(
        self,
        adapter: DispatchToolPort,
        *,
        system_allowlist: set[ToolName] | None = None,
        timeout_seconds: float = 1.0,
        max_attempts: int = 2,
        circuit_failure_threshold: int = 3,
        max_audit_events: int = 4096,
        max_tracked_traces: int = 4096,
    ) -> None:
        self.adapter = adapter
        self.system_allowlist = system_allowlist or set(ToolName)
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max_attempts
        self.circuit_failure_threshold = circuit_failure_threshold
        self.max_tracked_traces = max_tracked_traces
        self.audit_events: deque[ToolAuditEvent] = deque(maxlen=max_audit_events)
        self._calls_by_trace: Counter[str] = Counter()
        self._consecutive_failures: Counter[str] = Counter()

    # 经统一防护后读取指定工单快照。
    async def get_work_order_snapshot(
        self,
        work_order_id: str,
        context: RequestContext,
        skill: DispatchSkill,
    ) -> WorkOrderSnapshot:
        return await self._invoke(
            ToolName.GET_WORK_ORDER_SNAPSHOT,
            context,
            skill,
            {"work_order_id": work_order_id},
            lambda: self.adapter.get_work_order_snapshot(work_order_id, context),
        )

    # 校验工单租户后读取可供领域层筛选的工作人员快照。
    async def list_eligible_workers(
        self,
        work_order: WorkOrderSnapshot,
        context: RequestContext,
        skill: DispatchSkill,
    ) -> list[WorkerSnapshot]:
        self._require_tenant(work_order.tenant_id, context)
        return await self._invoke(
            ToolName.LIST_ELIGIBLE_WORKERS,
            context,
            skill,
            {"work_order_id": work_order.work_order_id},
            lambda: self.adapter.list_eligible_workers(work_order, context),
        )

    # 经统一防护后批量读取工作人员负载。
    async def get_worker_loads(
        self,
        worker_ids: list[str],
        context: RequestContext,
        skill: DispatchSkill,
    ) -> dict[str, int]:
        return await self._invoke(
            ToolName.GET_WORKER_LOADS,
            context,
            skill,
            {"worker_ids": worker_ids},
            lambda: self.adapter.get_worker_loads(worker_ids, context),
        )

    # 经统一防护后检索只读派单策略证据。
    async def search_dispatch_policy(
        self,
        query: str,
        context: RequestContext,
        skill: DispatchSkill,
    ) -> list[PolicyEvidence]:
        return await self._invoke(
            ToolName.SEARCH_DISPATCH_POLICY,
            context,
            skill,
            {"query": query},
            lambda: self.adapter.search_dispatch_policy(query, context),
        )

    # 校验写入命令合同后执行受权限和幂等约束的派单写入。
    async def create_assignment(
        self,
        command: AssignmentCommand,
        context: RequestContext,
        skill: DispatchSkill,
    ) -> AssignmentReceipt:
        self._validate_command(command, context)
        return await self._invoke(
            ToolName.CREATE_ASSIGNMENT,
            context,
            skill,
            command.model_dump(mode="json"),
            lambda: self.adapter.create_assignment(command, context),
            write=True,
        )

    # 校验派单标识后查询派单最终业务结果。
    async def get_assignment_outcome(
        self,
        dispatch_id: str,
        context: RequestContext,
        skill: DispatchSkill,
    ) -> AssignmentOutcome:
        if not dispatch_id:
            raise ToolContractError("get_assignment_outcome requires dispatch_id")
        return await self._invoke(
            ToolName.GET_ASSIGNMENT_OUTCOME,
            context,
            skill,
            {"dispatch_id": dispatch_id},
            lambda: self.adapter.get_assignment_outcome(dispatch_id, context),
        )

    # 校验派单标识后执行拥有独立权限的审计写入。
    async def publish_dispatch_audit(
        self,
        dispatch_id: str,
        payload: dict[str, Any],
        context: RequestContext,
        skill: DispatchSkill,
    ) -> AuditPublishResult:
        if not dispatch_id:
            raise ToolContractError("publish_dispatch_audit requires dispatch_id")
        return await self._invoke(
            ToolName.PUBLISH_DISPATCH_AUDIT,
            context,
            skill,
            {"dispatch_id": dispatch_id, "payload": payload},
            lambda: self.adapter.publish_dispatch_audit(dispatch_id, payload, context),
            audit_write=True,
        )

    # 统一执行授权、熔断、预算检查、有限重试、超时和审计记录。
    async def _invoke(
        self,
        tool_name: ToolName,
        context: RequestContext,
        skill: DispatchSkill,
        request: dict[str, Any],
        operation: Callable[[], Awaitable[T]],
        *,
        write: bool = False,
        audit_write: bool = False,
    ) -> T:
        # 调用前先完成权限授权：系统白名单、Skill 策略与请求权限交集
        self._authorize(tool_name, context, skill, write, audit_write)
        # 熔断检查：该工具连续失败次数达到阈值则直接拒绝，避免打爆下游
        if self._consecutive_failures[tool_name.value] >= self.circuit_failure_threshold:
            # 抛出熔断开路错误，跳过本次调用
            raise ToolCircuitOpenError(f"tool circuit is open: {tool_name}")

        # 有限重试：最多尝试 max_attempts 次
        for attempt in range(1, self.max_attempts + 1):
            # 每次尝试前校验请求截止时间并扣减调用预算
            self._check_budget_and_deadline(context)
            # 记录本次尝试的开始时刻，用于计算耗时
            started = time.perf_counter()
            # 执行调用并捕获可重试异常
            try:
                # 带超时执行底层操作，超过 timeout_seconds 视为超时
                response = await asyncio.wait_for(
                    operation(), timeout=self.timeout_seconds
                )
                # 调用成功：清零该工具的连续失败计数
                self._consecutive_failures[tool_name.value] = 0
                # 记录本次成功的审计事件
                self._record(
                    tool_name,
                    context,
                    attempt,
                    started,
                    request,
                    response=response,
                )
                # 成功则直接返回响应
                return response
            # 捕获依赖不可用与超时两类可重试异常
            except (DependencyUnavailableError, TimeoutError) as exc:
                # 失败：累加该工具的连续失败计数
                self._consecutive_failures[tool_name.value] += 1
                # 记录本次失败的审计事件
                self._record(
                    tool_name,
                    context,
                    attempt,
                    started,
                    request,
                    error=exc,
                )
                # 已到最大重试次数
                if attempt == self.max_attempts:
                    # 超时异常映射为超时业务错误并保留原始异常链
                    if isinstance(exc, TimeoutError):
                        # 抛出工具超时错误
                        raise ToolDeadlineExceededError(
                            f"tool timeout: {tool_name}"
                        ) from exc
                    # 非超时异常（依赖不可用）原样抛出
                    raise
        # 理论不可达：max_attempts 已穷尽但未返回或抛出
        raise AssertionError("unreachable")

    # 取系统白名单、冻结 Skill 策略和请求权限的交集完成授权。
    def _authorize(
        self,
        tool_name: ToolName,
        context: RequestContext,
        skill: DispatchSkill,
        write: bool,
        audit_write: bool,
    ) -> None:
        if tool_name not in self.system_allowlist:
            raise ToolAccessDeniedError(f"tool not in system allowlist: {tool_name}")
        declared = (
            skill.tool_policy.allowed_write_tools
            if write or audit_write
            else skill.tool_policy.allowed_read_tools
        )
        if tool_name.value not in declared:
            raise ToolAccessDeniedError(
                f"tool not allowed by frozen skill {skill.key}: {tool_name}"
            )
        if audit_write:
            required = AUDIT_PERMISSION
        elif write:
            required = WRITE_PERMISSION
        else:
            required = READ_PERMISSION
        if required not in context.permissions:
            raise ToolAccessDeniedError(
                f"request context lacks {required} for tool {tool_name}"
            )

    # 在每次尝试前校验请求截止时间并扣减工具调用预算。
    def _check_budget_and_deadline(self, context: RequestContext) -> None:
        if datetime.now(UTC) >= context.deadline:
            raise ToolDeadlineExceededError("dispatch request deadline exceeded")
        if (
            context.trace_id not in self._calls_by_trace
            and len(self._calls_by_trace) >= self.max_tracked_traces
        ):
            self._calls_by_trace.pop(next(iter(self._calls_by_trace)))
        self._calls_by_trace[context.trace_id] += 1
        if self._calls_by_trace[context.trace_id] > context.max_tool_calls:
            raise ToolRateLimitError("dispatch tool call budget exceeded")

    # 拒绝工具输入租户与请求上下文租户不一致的调用。
    @staticmethod
    def _require_tenant(tenant_id: str, context: RequestContext) -> None:
        if tenant_id != context.tenant_id:
            raise ToolContractError("tool input tenant does not match request context")

    # 校验派单命令的租户、事件血缘和幂等键。
    def _validate_command(
        self, command: AssignmentCommand, context: RequestContext
    ) -> None:
        self._require_tenant(command.tenant_id, context)
        if command.event_id != context.event_id:
            raise ToolContractError("assignment event_id does not match request context")
        if not command.idempotency_key:
            raise ToolContractError("assignment requires idempotency_key")

    # 将一次工具尝试的脱敏请求、响应、耗时和错误写入审计列表。
    def _record(
        self,
        tool_name: ToolName,
        context: RequestContext,
        attempt: int,
        started: float,
        request: dict[str, Any],
        *,
        response: Any | None = None,
        error: Exception | None = None,
    ) -> None:
        response_payload: dict[str, Any] | None
        if isinstance(response, BaseModel):
            response_payload = response.model_dump(mode="json")
        elif response is None:
            response_payload = None
        elif isinstance(response, list):
            response_payload = {"items": _jsonable(response)}
        elif isinstance(response, dict):
            response_payload = _redact(response)
        else:
            response_payload = {"value": str(response)}
        self.audit_events.append(
            ToolAuditEvent(
                trace_id=context.trace_id,
                tenant_id=context.tenant_id,
                event_id=context.event_id,
                tool_name=tool_name,
                attempt=attempt,
                success=error is None,
                duration_ms=round((time.perf_counter() - started) * 1000, 3),
                request=_redact(request),
                response=_redact(response_payload) if response_payload else None,
                error_type=type(error).__name__ if error else None,
            )
        )


# 递归把 Pydantic 模型和容器转换为 JSON 可序列化结构。
def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    return value


# 递归遮蔽字典及嵌套列表中的敏感字段值。
def _redact(value: dict[str, Any]) -> dict[str, Any]:
    redacted: dict[str, Any] = {}
    for key, item in value.items():
        if key.lower() in SENSITIVE_KEYS:
            redacted[key] = "[REDACTED]"
        elif isinstance(item, dict):
            redacted[key] = _redact(item)
        elif isinstance(item, list):
            redacted[key] = [
                _redact(element) if isinstance(element, dict) else element
                for element in item
            ]
        else:
            redacted[key] = item
    return redacted
