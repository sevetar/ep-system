from __future__ import annotations

import asyncio
import json
import time
from collections import Counter
from typing import Any

from flowfix_agent.tools.errors import (
    ToolAuthorizationError,
    ToolExecutionError,
    ToolInputError,
)
from flowfix_agent.tools.models import ToolCall, ToolContext, ToolObservation
from flowfix_agent.tools.policy import ToolPolicy
from flowfix_agent.tools.resolver import ToolResolver


# 统一工具网关：解析、授权、预算、输入/输出校验、超时重试与 Observation 裁剪。
class ToolGateway:
    # 初始化网关：绑定解析器与策略，配置超时、裁剪上限和最大尝试次数。
    def __init__(
        self,
        resolver: ToolResolver,
        policy: ToolPolicy | None = None,
        *,
        timeout_seconds: float = 5,
        max_observation_chars: int = 16_000,
        max_attempts: int = 2,
        max_tracked_traces: int = 4096,
    ) -> None:
        self.resolver = resolver
        self.policy = policy or ToolPolicy()
        self.timeout_seconds = timeout_seconds
        self.max_observation_chars = max_observation_chars
        self.max_attempts = max_attempts
        self.max_tracked_traces = max_tracked_traces
        self._calls: Counter[str] = Counter()

    # 执行一次工具调用：解析并授权、校验参数与预算，超时重试后校验输出并裁剪。
    async def invoke(
        self,
        call: ToolCall,
        context: ToolContext,
        *,
        preferred_provider: str | None = None,
    ) -> ToolObservation:
        # 阶段一：能力解析与授权。Resolver 按能力名定位注册的 Provider（可指定首选实现），
        # Policy 校验该能力是否在链路允许范围内、参数与租户是否合法。
        registration = self.resolver.resolve(
            call.capability, preferred_provider=preferred_provider
        )
        self.policy.authorize(registration.spec, context)
        # 阶段二：调用预算。按 trace 维度累计调用次数，超过上限先淘汰最旧追踪，避免无界增长。
        if context.trace_id not in self._calls and len(self._calls) >= self.max_tracked_traces:
            self._calls.pop(next(iter(self._calls)))
        self._calls[context.trace_id] += 1
        if self._calls[context.trace_id] > context.max_tool_calls:
            raise ToolAuthorizationError("tool call budget exceeded")
        # 阶段三：输入校验。按能力声明的输入 Schema 检查参数结构与必填字段，
        # 防止坏参数进入 Provider。
        self._validate_object(call.arguments, registration.spec.input_schema, ToolInputError)

        started = time.perf_counter()
        payload: Any | None = None
        # 阶段四：执行与超时重试。整体包在 wait_for 超时内，仅对可重试的瞬时故障（超时/连接）
        # 重试至多 max_attempts 次；业务失败（ToolExecutionError）立即抛出，不重试。
        for attempt in range(1, self.max_attempts + 1):
            try:
                payload = await asyncio.wait_for(
                    registration.provider.invoke(
                        call.capability, call.arguments, context
                    ),
                    timeout=self.timeout_seconds,
                )
                break
            except (TimeoutError, ConnectionError) as exc:
                if attempt == self.max_attempts:
                    raise ToolExecutionError(
                        f"transient tool failure after {attempt} attempts: {call.capability}"
                    ) from exc
            except ToolExecutionError:
                raise
            except Exception as exc:
                raise ToolExecutionError(
                    f"provider failed: {call.capability}: {type(exc).__name__}"
                ) from exc
        # Provider 未返回任何负载视为异常（如重试后仍无有效结果）。
        if payload is None:
            raise ToolExecutionError(f"provider returned no payload: {call.capability}")
        # 阶段五：输出校验。按能力声明的输出 Schema 校验返回结构，防止脏负载进入下游。
        self._validate_object(
            payload, registration.spec.output_schema, ToolExecutionError
        )

        # 阶段六：观察裁剪。超长负载被序列化后截断并标记，避免撑爆模型上下文。
        cleaned, truncated = self._sanitize(
            payload, registration.spec.max_observation_chars
        )
        # 阶段七：组装 Observation 返回，含调用方、能力、实际 Provider、负载与耗时。
        return ToolObservation(
            call_id=call.call_id,
            capability=call.capability,
            provider=registration.provider.provider_id,
            success=True,
            payload=cleaned,
            truncated=truncated,
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
        )

    # 将负载 JSON 序列化，超出上限时裁剪并标记 truncated。
    # 优先使用能力声明的上限；结构化能力（如 EvidenceBundle）可用更大的上限，
    # 其余能力沿用网关默认值以保护模型上下文。
    def _sanitize(self, payload: Any, max_chars: int | None = None) -> tuple[Any, bool]:
        limit = max_chars or self.max_observation_chars
        encoded = json.dumps(payload, ensure_ascii=False, default=str)
        if len(encoded) <= limit:
            return payload, False
        return {"truncated_text": encoded[:limit]}, True

    # 按 JSON Schema 规则校验负载类型、必填字段与字段类型。
    @staticmethod
    def _validate_object(payload: Any, schema: dict[str, Any], error_type: type[Exception]) -> None:
        if schema.get("type") == "object" and not isinstance(payload, dict):
            raise error_type("payload must be an object")
        if not isinstance(payload, dict):
            return
        required = schema.get("required", [])
        missing = [field for field in required if field not in payload]
        if missing:
            raise error_type(f"missing required fields: {missing}")
        properties = schema.get("properties", {})
        type_map = {
            "string": str,
            "integer": int,
            "number": (int, float),
            "boolean": bool,
            "array": list,
            "object": dict,
        }
        for field, value in payload.items():
            expected_name = properties.get(field, {}).get("type")
            expected = type_map.get(expected_name)
            if expected and not isinstance(value, expected):
                raise error_type(f"field {field} must be {expected_name}")
