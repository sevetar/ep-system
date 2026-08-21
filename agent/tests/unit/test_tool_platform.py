from typing import Any

import pytest

from flowfix_agent.core.models import RequestScope
from flowfix_agent.retrieval.models import RetrievalOptions
from flowfix_agent.tools import (
    CapabilityAccess,
    ToolCall,
    ToolContext,
    ToolGateway,
    ToolRegistry,
    ToolResolver,
    ToolSpec,
)
from flowfix_agent.tools.errors import (
    CapabilityNotFoundError,
    ToolAuthorizationError,
    ToolExecutionError,
    ToolInputError,
)
from flowfix_agent.tools.models import ToolObservation
from flowfix_agent.tools.providers import FakeMCPProvider, LocalFunctionProvider
from flowfix_agent.tools.providers.retrieval import RetrievalCapabilityClient


async def echo(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    return {"value": arguments["value"], "tenant": context.tenant_id}


def spec(access: CapabilityAccess = CapabilityAccess.READ) -> ToolSpec:
    return ToolSpec(
        name="test.echo",
        version="1",
        description="echo",
        access=access,
        input_schema={
            "type": "object",
            "required": ["value"],
            "properties": {"value": {"type": "string"}},
        },
        output_schema={
            "type": "object",
            "required": ["value", "tenant"],
        },
    )


def context() -> ToolContext:
    return ToolContext(
        trace_id="trace-1",
        tenant_id="tenant-a",
        chain="investigation",
        role="worker",
        permissions={"tool:read"},
        allowed_capabilities={"test.echo"},
    )


@pytest.mark.parametrize("provider_type", [LocalFunctionProvider, FakeMCPProvider])
async def test_local_and_fake_mcp_providers_share_contract(provider_type):
    registry = ToolRegistry()
    registry.register(spec(), provider_type({"test.echo": echo}))
    observation = await ToolGateway(ToolResolver(registry)).invoke(
        ToolCall(capability="test.echo", arguments={"value": "ok"}, call_id="c1"),
        context(),
    )

    assert observation.payload == {"value": "ok", "tenant": "tenant-a"}
    assert observation.untrusted is True


async def test_gateway_rejects_invalid_arguments_before_provider():
    registry = ToolRegistry()
    registry.register(spec(), FakeMCPProvider({"test.echo": echo}))

    with pytest.raises(ToolInputError):
        await ToolGateway(ToolResolver(registry)).invoke(
            ToolCall(capability="test.echo", arguments={}, call_id="c1"), context()
        )


async def test_investigation_cannot_receive_write_capability():
    registry = ToolRegistry()
    registry.register(spec(CapabilityAccess.WRITE), FakeMCPProvider({"test.echo": echo}))

    with pytest.raises(ToolAuthorizationError):
        await ToolGateway(ToolResolver(registry)).invoke(
            ToolCall(capability="test.echo", arguments={"value": "x"}, call_id="c1"),
            context(),
        )


def big_spec(max_observation_chars: int | None = None) -> ToolSpec:
    return ToolSpec(
        name="test.big",
        version="1",
        description="big",
        max_observation_chars=max_observation_chars,
        input_schema={
            "type": "object",
            "required": ["value"],
            "properties": {"value": {"type": "string"}},
        },
        output_schema={
            "type": "object",
            "required": ["blob"],
        },
    )


# 返回超长负载的异步处理器，用于验证观察裁剪行为。
async def big_blob(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    return {"blob": "x" * 20_000}


def big_context() -> ToolContext:
    return ToolContext(
        trace_id="trace-1",
        tenant_id="tenant-a",
        chain="investigation",
        role="worker",
        permissions={"tool:read"},
        allowed_capabilities={"test.big"},
    )


# 结构化能力可用更大观察上限：负载超网关默认但低于能力上限时不再裁剪。
async def test_gateway_honors_spec_observation_cap():
    registry = ToolRegistry()
    registry.register(
        big_spec(max_observation_chars=200_000),
        FakeMCPProvider({"test.big": big_blob}),
    )
    gateway = ToolGateway(ToolResolver(registry), max_observation_chars=16_000)

    observation = await gateway.invoke(
        ToolCall(capability="test.big", arguments={"value": "ok"}, call_id="c1"),
        big_context(),
    )

    assert observation.truncated is False
    assert len(observation.payload["blob"]) == 20_000


# 未声明上限的能力仍沿用网关默认上限，超限时裁剪并标记 truncated。
async def test_gateway_default_cap_still_truncates():
    registry = ToolRegistry()
    registry.register(
        big_spec(),
        FakeMCPProvider({"test.big": big_blob}),
    )

    observation = await ToolGateway(ToolResolver(registry)).invoke(
        ToolCall(capability="test.big", arguments={"value": "ok"}, call_id="c1"),
        big_context(),
    )

    assert observation.truncated is True
    assert "truncated_text" in observation.payload


# 检索能力客户端在负载被裁剪时给出明确错误，而不是用残缺负载触发模型校验崩溃。
async def test_retrieval_capability_raises_on_truncated_observation(monkeypatch):
    registry = ToolRegistry()
    registry.register(
        big_spec(max_observation_chars=200_000),
        FakeMCPProvider({"test.big": big_blob}),
    )
    gateway = ToolGateway(ToolResolver(registry), max_observation_chars=16_000)
    client = RetrievalCapabilityClient(gateway)
    scope = RequestScope(tenant_id="tenant-eval", visibility="tenant")

    # 绕过解析，直接注入一个已裁剪的观察以隔离失败路径。
    async def fake_invoke(call, context, **kwargs):
        return ToolObservation(
            call_id=call.call_id,
            capability=call.capability,
            provider="fake",
            success=True,
            payload={"truncated_text": "..."},
            truncated=True,
        )

    monkeypatch.setattr(gateway, "invoke", fake_invoke)

    with pytest.raises(ToolExecutionError):
        await client.retrieve("查询", scope, RetrievalOptions(), "trace")


# ---- 未知 capability fail-closed 覆盖（亮点 4：Tool Platform 最小权限） ----

# 注册表对未注册的 capability 直接抛 CapabilityNotFoundError，而不是静默返回空集。
async def test_registry_raises_capability_not_found_for_unknown_capability():
    registry = ToolRegistry()

    with pytest.raises(CapabilityNotFoundError):
        registry.registrations("some-unknown-capability")


# 记录被调用的 spy provider，用于证明 fail-closed 路径在解析阶段就终止、不触碰任何 Provider。
class RecordingProvider:
    provider_id = "recording"

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def invoke(self, capability, arguments, context):
        self.calls.append(capability)
        return {"ok": True}


# 网关对未知 capability 第一步（resolver.resolve）即抛 CapabilityNotFoundError，
# 即使显式指定 preferred_provider 也不会触发任何 Provider 执行。
async def test_gateway_rejects_unknown_capability_fail_closed_without_calling_provider():
    registry = ToolRegistry()
    recording = RecordingProvider()
    registry.register(spec(), recording)

    with pytest.raises(CapabilityNotFoundError):
        await ToolGateway(ToolResolver(registry)).invoke(
            ToolCall(capability="some-unknown-capability", arguments={}, call_id="c1"),
            context(),
            preferred_provider="recording",
        )

    assert recording.calls == []
