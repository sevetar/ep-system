from __future__ import annotations

import json

from flowfix_agent.investigation.models import (
    InvestigationRequest,
    InvestigationResult,
    StopReason,
)
from flowfix_agent.investigation.ports import InvestigationDecisionPort
from flowfix_agent.tools.errors import ToolInputError, ToolPlatformError
from flowfix_agent.tools.gateway import ToolGateway
from flowfix_agent.tools.models import ToolCall, ToolContext, ToolObservation, ToolSpec
from flowfix_agent.tools.registry import ToolRegistry


# 有界只读调查循环：重复决策-调用-观测，直到完成、预算耗尽、证据不足或阻断。
class InvestigationLoop:
    # 绑定决策端口、能力注册表与统一网关。
    def __init__(
        self,
        decision: InvestigationDecisionPort,
        registry: ToolRegistry,
        gateway: ToolGateway,
    ) -> None:
        self.decision = decision
        self.registry = registry
        self.gateway = gateway

    # 执行调查循环并返回 InvestigationResult。
    async def run(self, request: InvestigationRequest) -> InvestigationResult:
        # 按请求允许的 capability 过滤注册表，决策端口只能看到被授权的工具。
        specs = [
            spec for spec in self.registry.specs() if spec.name in request.allowed_capabilities
        ]
        # observations 累积调用记录作为证据；seen 用于去重相同（能力+参数）的调用。
        observations: list[ToolObservation] = []
        seen: set[str] = set()
        # 统一的只读调用上下文：调查角色只有 tool:read 权限。
        context = ToolContext(
            trace_id=request.trace_id,
            tenant_id=request.tenant_id,
            chain="investigation",
            role="investigator",
            permissions={"tool:read"},
            allowed_capabilities=request.allowed_capabilities,
            max_tool_calls=request.max_steps,
        )
        # 有界循环：最多执行 max_steps 步。
        for step in range(1, request.max_steps + 1):
            # 1) 决策：端口基于已有观测决定下一步（调用工具、给出结论或停止）。
            decision = await self.decision.decide(request, specs, observations)
            # 2) 决策端口不再调用工具：按终止原因返回结果。
            if decision.tool_call is None:
                reason = decision.stop_reason or (
                    StopReason.COMPLETED
                    if decision.conclusion
                    else StopReason.INSUFFICIENT_EVIDENCE
                )
                return InvestigationResult(
                    incident_id=request.incident_id,
                    trace_id=request.trace_id,
                    conclusion=decision.conclusion or "现有证据不足，无法形成可靠结论。",
                    observations=observations,
                    evidence_refs=self._evidence_refs(observations),
                    uncertainty=decision.uncertainty,
                    stop_reason=reason,
                    steps=step,
                )
            # 模型输出是不可信输入。调用工具前由运行时绑定租户与 trace，
            # 并为声明了 options 的工具补默认对象，模型不能决定安全上下文。
            spec = next(
                (item for item in specs if item.name == decision.tool_call.capability), None
            )
            if spec is None:
                return self._stopped(
                    request,
                    observations,
                    StopReason.BLOCKED,
                    step,
                    f"工具能力未获授权：{decision.tool_call.capability}",
                )
            tool_call = self._bind_runtime_arguments(decision.tool_call, spec, request)
            # 3) 调用前先去重：以（能力+序列化参数）作为签名，重复调用直接阻断。
            arguments_key = json.dumps(tool_call.arguments, sort_keys=True, ensure_ascii=False)
            signature = f"{tool_call.capability}:{arguments_key}"
            if signature in seen:
                return self._stopped(
                    request,
                    observations,
                    StopReason.BLOCKED,
                    step,
                    "检测到重复工具调用。",
                )
            seen.add(signature)
            # 4) 经统一网关执行只读工具调用并记录观测；异常也转成失败观测或阻断。
            try:
                observations.append(await self.gateway.invoke(tool_call, context))
            except ToolInputError as exc:
                observations.append(
                    ToolObservation(
                        call_id=tool_call.call_id,
                        capability=tool_call.capability,
                        provider="gateway",
                        success=False,
                        error_code="INVALID_ARGUMENTS",
                        error_message=str(exc),
                    )
                )
            except ToolPlatformError as exc:
                return self._stopped(request, observations, StopReason.BLOCKED, step, str(exc))
        # 5) 预算耗尽：步骤达到上限仍无结论时按 BUDGET_EXHAUSTED 终止。
        return self._stopped(
            request,
            observations,
            StopReason.BUDGET_EXHAUSTED,
            request.max_steps,
            "调查达到最大步骤预算。",
        )

    # 将模型建议参数绑定到可信请求上下文，同时保留非安全相关的检索过滤条件。
    @staticmethod
    def _bind_runtime_arguments(
        call: ToolCall,
        spec: ToolSpec,
        request: InvestigationRequest,
    ) -> ToolCall:
        arguments = dict(call.arguments)
        properties = spec.input_schema.get("properties", {})
        if "scope" in properties:
            model_scope = arguments.get("scope")
            scope = dict(model_scope) if isinstance(model_scope, dict) else {}
            scope["tenant_id"] = request.tenant_id
            arguments["scope"] = scope
        if "trace_id" in properties:
            arguments["trace_id"] = request.trace_id
        if "options" in properties and not isinstance(arguments.get("options"), dict):
            arguments["options"] = {}
        return call.model_copy(update={"arguments": arguments})

    # 收集成功观测的调用标识作为证据引用。
    @staticmethod
    def _evidence_refs(observations: list[ToolObservation]) -> list[str]:
        return [item.call_id for item in observations if item.success]

    # 构造提前终止的调查结果。
    @classmethod
    def _stopped(
        cls,
        request: InvestigationRequest,
        observations: list[ToolObservation],
        reason: StopReason,
        steps: int,
        conclusion: str,
    ) -> InvestigationResult:
        return InvestigationResult(
            incident_id=request.incident_id,
            trace_id=request.trace_id,
            conclusion=conclusion,
            observations=observations,
            evidence_refs=cls._evidence_refs(observations),
            stop_reason=reason,
            steps=steps,
        )
