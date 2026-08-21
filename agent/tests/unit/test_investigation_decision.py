import json

import pytest
from langchain_core.messages import AIMessage

from flowfix_agent.adapters.investigation_decision import (
    InvestigationDecisionError,
    LangChainInvestigationDecision,
)
from flowfix_agent.investigation.models import InvestigationRequest
from flowfix_agent.tools.models import (
    CapabilityAccess,
    ToolSpec,
)


# 模拟可注入的异步链，按顺序返回固定输出。
class FakeChain:
    def __init__(self, outputs: list[str]) -> None:
        self.outputs = list(outputs)
        self.calls: list[dict] = []

    async def ainvoke(self, variables: dict) -> str:
        self.calls.append(variables)
        if not self.outputs:
            raise AssertionError("unexpected extra chain call")
        return self.outputs.pop(0)


# 模拟可注入的原生工具调用链，按顺序返回固定 AIMessage。
class FakeNativeChain:
    def __init__(self, outputs: list[AIMessage]) -> None:
        self.outputs = list(outputs)
        self.calls: list[dict] = []

    async def ainvoke(self, variables: dict) -> AIMessage:
        self.calls.append(variables)
        if not self.outputs:
            raise AssertionError("unexpected extra chain call")
        return self.outputs.pop(0)


def _request() -> InvestigationRequest:
    return InvestigationRequest(
        incident_id="i1",
        tenant_id="tenant-1",
        thread_id="thread-1",
        goal="定位设备停机根因",
        trace_id="trace-1",
        allowed_capabilities={"knowledge.search"},
        max_steps=6,
    )


def _spec() -> ToolSpec:
    return ToolSpec(
        name="knowledge.search",
        version="1.0.0",
        description="检索运维知识库",
        access=CapabilityAccess.READ,
        input_schema={
            "type": "object",
            "properties": {"query": {"type": "string"}},
        },
        output_schema={"type": "object"},
    )


def _tool_call_json() -> str:
    return json.dumps(
        {
            "tool_call": {
                "capability": "knowledge.search",
                "arguments": {"query": "电源模块故障"},
                "call_id": "whatever",
            },
            "conclusion": None,
            "uncertainty": [],
            "stop_reason": None,
        },
        ensure_ascii=False,
    )


def _final_json() -> str:
    return json.dumps(
        {
            "tool_call": None,
            "conclusion": "根因为电源模块老化。",
            "uncertainty": ["备件到货时间"],
            "stop_reason": "completed",
        },
        ensure_ascii=False,
    )


def _build(native_tools: bool = False) -> LangChainInvestigationDecision:
    return LangChainInvestigationDecision(
        "k", "https://api.example.com/v1", "m", 10, native_tools=native_tools
    )


# 验证合法工具调用直接解析，且 call_id 被确定性覆盖。
async def test_decision_parses_valid_tool_call_without_repair():
    decision_maker = _build()
    decision_maker._chain = FakeChain([_tool_call_json()])
    decision_maker._repair_chain = FakeChain([])

    decision = await decision_maker.decide(_request(), [_spec()], [])

    assert decision.tool_call is not None
    assert decision.tool_call.capability == "knowledge.search"
    assert decision.tool_call.call_id == "trace-1:dec:1"
    assert decision_maker._repair_chain.calls == []


# 验证合法收尾决策直接解析：结论加停止原因。
async def test_decision_parses_valid_final_without_repair():
    decision_maker = _build()
    decision_maker._chain = FakeChain([_final_json()])
    decision_maker._repair_chain = FakeChain([])

    decision = await decision_maker.decide(_request(), [_spec()], [])

    assert decision.tool_call is None
    assert decision.conclusion == "根因为电源模块老化。"
    assert decision.stop_reason == "completed"
    assert decision_maker._repair_chain.calls == []


# 验证越界能力触发 repair：选择工具列表之外的能力。
async def test_decision_repairs_outside_capability():
    decision_maker = _build()
    raw = json.dumps(
        {
            "tool_call": {
                "capability": "assignment.create",
                "arguments": {},
                "call_id": "x",
            },
            "conclusion": None,
            "uncertainty": [],
            "stop_reason": None,
        }
    )
    decision_maker._chain = FakeChain([raw])
    decision_maker._repair_chain = FakeChain([_tool_call_json()])

    decision = await decision_maker.decide(_request(), [_spec()], [])

    assert decision.tool_call.capability == "knowledge.search"
    assert len(decision_maker._repair_chain.calls) == 1


# 验证非法 JSON 走一次 repair 并成功。
async def test_decision_repairs_invalid_json_once():
    decision_maker = _build()
    decision_maker._chain = FakeChain(["not json"])
    decision_maker._repair_chain = FakeChain([_final_json()])

    decision = await decision_maker.decide(_request(), [_spec()], [])

    assert decision.tool_call is None
    assert decision.stop_reason == "completed"
    assert len(decision_maker._repair_chain.calls) == 1


# 验证两次输出都非法时 fail-closed 抛出异常。
async def test_decision_fail_closed_after_repair():
    decision_maker = _build()
    decision_maker._chain = FakeChain(["not json"])
    decision_maker._repair_chain = FakeChain(["still not json"])

    with pytest.raises(InvestigationDecisionError):
        await decision_maker.decide(_request(), [_spec()], [])


# 验证收尾决策缺 conclusion 且缺 stop_reason 时触发 repair。
async def test_decision_repairs_empty_final():
    decision_maker = _build()
    raw = json.dumps(
        {
            "tool_call": None,
            "conclusion": None,
            "uncertainty": [],
            "stop_reason": None,
        }
    )
    decision_maker._chain = FakeChain([raw])
    decision_maker._repair_chain = FakeChain([_final_json()])

    decision = await decision_maker.decide(_request(), [_spec()], [])

    assert decision.conclusion is not None
    assert len(decision_maker._repair_chain.calls) == 1


# 验证 stop_reason 使用非终态原因（如 blocked）时触发 repair。
async def test_decision_repairs_invalid_stop_reason():
    decision_maker = _build()
    raw = json.dumps(
        {
            "tool_call": None,
            "conclusion": "结论",
            "uncertainty": [],
            "stop_reason": "blocked",
        }
    )
    decision_maker._chain = FakeChain([raw])
    decision_maker._repair_chain = FakeChain([_final_json()])

    decision = await decision_maker.decide(_request(), [_spec()], [])

    assert decision.stop_reason == "completed"
    assert len(decision_maker._repair_chain.calls) == 1


# 验证防御性剥离 markdown 代码围栏后再解析。
async def test_decision_strips_code_fence():
    decision_maker = _build()
    decision_maker._chain = FakeChain([f"```json\n{_tool_call_json()}\n```"])
    decision_maker._repair_chain = FakeChain([])

    decision = await decision_maker.decide(_request(), [_spec()], [])

    assert decision.tool_call.call_id == "trace-1:dec:1"


# 原生 function calling：合法 tool_call 直接解析且 call_id 被确定性覆盖。
async def test_native_tools_parses_valid_tool_call():
    decision_maker = _build(native_tools=True)
    decision_maker._native_chain = FakeNativeChain(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "knowledge.search",
                        "args": {"query": "电源模块故障"},
                        "id": "call-abc",
                    }
                ],
            )
        ]
    )
    decision_maker._repair_chain = FakeChain([])

    decision = await decision_maker.decide(_request(), [_spec()], [])

    assert decision.tool_call is not None
    assert decision.tool_call.capability == "knowledge.search"
    assert decision.tool_call.arguments == {"query": "电源模块故障"}
    assert decision.tool_call.call_id == "trace-1:dec:1"
    assert decision_maker._repair_chain.calls == []


# 原生 function calling：空参数 {} 是合法工具调用，不应被误判为缺失。
async def test_native_tools_parses_empty_arguments():
    decision_maker = _build(native_tools=True)
    decision_maker._native_chain = FakeNativeChain(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "knowledge.search", "args": {}, "id": "call-1"}
                ],
            )
        ]
    )
    decision_maker._repair_chain = FakeChain([])

    decision = await decision_maker.decide(_request(), [_spec()], [])

    assert decision.tool_call is not None
    assert decision.tool_call.arguments == {}
    assert decision.tool_call.call_id == "trace-1:dec:1"
    assert decision_maker._repair_chain.calls == []


# 原生 function calling：越权 capability 被拒绝，修复后仍失败则 fail-closed。
async def test_native_tools_fail_closed_on_outside_capability():
    decision_maker = _build(native_tools=True)
    decision_maker._native_chain = FakeNativeChain(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "assignment.create", "args": {}, "id": "call-1"}
                ],
            )
        ]
    )
    decision_maker._repair_chain = FakeChain(["still not json"])

    with pytest.raises(InvestigationDecisionError):
        await decision_maker.decide(_request(), [_spec()], [])


# 原生 function calling：越权 capability 触发一次 repair，修复输出合法 tool_call。
async def test_native_tools_repairs_outside_capability():
    decision_maker = _build(native_tools=True)
    decision_maker._native_chain = FakeNativeChain(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "assignment.create", "args": {}, "id": "call-1"}
                ],
            )
        ]
    )
    decision_maker._repair_chain = FakeChain([_tool_call_json()])

    decision = await decision_maker.decide(_request(), [_spec()], [])

    assert decision.tool_call.capability == "knowledge.search"
    assert len(decision_maker._repair_chain.calls) == 1


# 原生 function calling：非法 arguments JSON 被拒绝并触发一次 repair。
async def test_native_tools_repairs_invalid_arguments():
    decision_maker = _build(native_tools=True)
    decision_maker._native_chain = FakeNativeChain(
        [
            AIMessage(
                content="",
                additional_kwargs={
                    "tool_calls": [
                        {
                            "id": "call-2",
                            "type": "function",
                            "function": {
                                "name": "knowledge.search",
                                "arguments": "{not valid json",
                            },
                        }
                    ]
                },
            )
        ]
    )
    decision_maker._repair_chain = FakeChain([_final_json()])

    decision = await decision_maker.decide(_request(), [_spec()], [])

    assert decision.tool_call is None
    assert decision.conclusion == "根因为电源模块老化。"
    assert len(decision_maker._repair_chain.calls) == 1


# 原生 function calling：无 tool_calls 时从 content 解析收尾结论。
async def test_native_tools_parses_final_content():
    decision_maker = _build(native_tools=True)
    decision_maker._native_chain = FakeNativeChain([AIMessage(content=_final_json())])
    decision_maker._repair_chain = FakeChain([])

    decision = await decision_maker.decide(_request(), [_spec()], [])

    assert decision.tool_call is None
    assert decision.conclusion == "根因为电源模块老化。"
    assert decision.stop_reason == "completed"
    assert decision_maker._repair_chain.calls == []
