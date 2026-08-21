from typing import Any

from flowfix_agent.investigation.loop import InvestigationLoop
from flowfix_agent.investigation.models import (
    AgentDecision,
    InvestigationRequest,
    StopReason,
)
from flowfix_agent.tools import ToolCall, ToolContext, ToolGateway, ToolRegistry, ToolResolver
from flowfix_agent.tools.providers import FakeMCPProvider
from flowfix_agent.tools.providers.retrieval import knowledge_search_spec


async def search(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    return {
        "trace_id": context.trace_id,
        "selected_evidence": [{"source": "manual"}],
        "sufficient": True,
    }


class FakeDecision:
    async def decide(self, request, specs, observations):
        if not observations:
            return AgentDecision(
                tool_call=ToolCall(
                    capability="knowledge.search",
                    arguments={
                        "query": request.goal,
                        "scope": {},
                        "options": {},
                        "trace_id": request.trace_id,
                    },
                    call_id="call-1",
                )
            )
        return AgentDecision(
            conclusion="手册证据支持检查电源。",
            stop_reason=StopReason.COMPLETED,
        )


async def test_bounded_investigation_returns_structured_result():
    registry = ToolRegistry()
    registry.register(
        knowledge_search_spec(), FakeMCPProvider({"knowledge.search": search})
    )
    loop = InvestigationLoop(
        FakeDecision(), registry, ToolGateway(ToolResolver(registry))
    )

    result = await loop.run(
        InvestigationRequest(
            incident_id="i1",
            tenant_id="t1",
            thread_id="th1",
            goal="调查设备 DEV-1",
            trace_id="trace-1",
            allowed_capabilities={"knowledge.search"},
        )
    )

    assert result.stop_reason is StopReason.COMPLETED
    assert result.evidence_refs == ["call-1"]
    assert result.steps == 2


class UntrustedArgumentsDecision:
    def __init__(self, arguments: dict[str, Any]) -> None:
        self.arguments = arguments

    async def decide(self, request, specs, observations):
        if observations:
            return AgentDecision(
                conclusion="已取得可信检索证据。",
                stop_reason=StopReason.COMPLETED,
            )
        return AgentDecision(
            tool_call=ToolCall(
                capability="knowledge.search",
                arguments=self.arguments,
                call_id="model-call-id",
            )
        )


async def _run_with_untrusted_arguments(arguments: dict[str, Any]):
    captured: dict[str, Any] = {}

    async def capture(arguments, context):
        captured.update(arguments)
        return {
            "trace_id": context.trace_id,
            "selected_evidence": [{"source": "manual"}],
            "sufficient": True,
        }

    registry = ToolRegistry()
    registry.register(
        knowledge_search_spec(), FakeMCPProvider({"knowledge.search": capture})
    )
    loop = InvestigationLoop(
        UntrustedArgumentsDecision(arguments),
        registry,
        ToolGateway(ToolResolver(registry)),
    )
    result = await loop.run(
        InvestigationRequest(
            incident_id="i1",
            tenant_id="public",
            thread_id="th1",
            goal="调查设备 DEV-1",
            trace_id="trusted-trace",
            allowed_capabilities={"knowledge.search"},
        )
    )
    return result, captured


async def test_runtime_overrides_model_tenant_and_trace():
    result, captured = await _run_with_untrusted_arguments(
        {
            "query": "电源模块故障",
            "scope": {"tenant_id": "t", "visibility": "tenant"},
            "options": {},
            "trace_id": "model-trace",
        }
    )

    assert result.stop_reason is StopReason.COMPLETED
    assert result.evidence_refs == ["model-call-id"]
    assert captured["scope"] == {"tenant_id": "public", "visibility": "tenant"}
    assert captured["trace_id"] == "trusted-trace"


async def test_runtime_supplies_missing_options():
    result, captured = await _run_with_untrusted_arguments(
        {
            "query": "电源模块故障",
            "scope": {"tenant_id": "wrong"},
            "trace_id": "wrong-trace",
        }
    )

    assert result.stop_reason is StopReason.COMPLETED
    assert captured["options"] == {}


# 决策端口请求未注册的 capability 时，调查循环以结构化 BLOCKED 结果拒绝，
# 不向上抛异常（API 层不会因此变成 500），且在触达 Provider 前被拦下。
async def test_loop_rejects_unknown_capability_as_structured_block():
    registry = ToolRegistry()
    calls: list[str] = []

    async def capture(arguments, context):
        calls.append(context.trace_id)
        return {
            "trace_id": context.trace_id,
            "selected_evidence": [{"source": "manual"}],
            "sufficient": True,
        }

    registry.register(
        knowledge_search_spec(), FakeMCPProvider({"knowledge.search": capture})
    )

    class UnknownDecision:
        async def decide(self, request, specs, observations):
            return AgentDecision(
                tool_call=ToolCall(
                    capability="some-unknown-capability",
                    arguments={},
                    call_id="call-x",
                )
            )

    loop = InvestigationLoop(
        UnknownDecision(), registry, ToolGateway(ToolResolver(registry))
    )
    result = await loop.run(
        InvestigationRequest(
            incident_id="i1",
            tenant_id="t1",
            thread_id="th1",
            goal="调查未知能力",
            trace_id="trace-1",
            allowed_capabilities={"knowledge.search"},
        )
    )

    assert result.stop_reason is StopReason.BLOCKED
    assert "some-unknown-capability" in result.conclusion
    assert calls == []  # 未知能力在授权/解析阶段被拦下，未触碰任何 Provider
