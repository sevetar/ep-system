from __future__ import annotations

import json
from typing import Any

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import ValidationError

from flowfix_agent.adapters.models import strip_code_fence
from flowfix_agent.core.errors import FlowFixError
from flowfix_agent.investigation.models import (
    AgentDecision,
    InvestigationRequest,
)
from flowfix_agent.tools.models import ToolCall, ToolObservation, ToolSpec

# 注意：JSON 示例中的花括号需转义为双花括号，避免被模板解析为占位符。
_SCHEMA_DOC = """\
JSON 结构如下：
{{
  "tool_call": {{
    "capability": "knowledge.search",
    "arguments": {{"query": "检索关键词", "scope": {{"tenant_id": "t", "visibility": "tenant"}}}},
    "call_id": "call-id"
  }},
  "conclusion": null,
  "uncertainty": [],
  "stop_reason": null
}}
"""
# 不带工具调用时的收尾结构：conclusion 与 stop_reason 至少一个非空。
_FINAL_SCHEMA_DOC = """\
JSON 结构如下：
{{
  "tool_call": null,
  "conclusion": "调查结论",
  "uncertainty": ["不确定点"],
  "stop_reason": "completed"
}}
"""

# 决策允许出现的收尾停止原因，其余原因由调查循环自身判定。
_TERMINAL_STOP_REASONS = {"completed", "insufficient_evidence"}


# 从 AIMessage.content 中提取纯文本，兼容字符串与多模态文本块列表。
def _extract_message_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
        return "".join(parts).strip()
    return ""


# 提取 AIMessage 中的工具调用列表并规范为 name/arguments/id 结构。
# 优先读 LangChain 解析后的 tool_calls；为空时兜底读 additional_kwargs 中的原始
# OpenAI 结构（function.arguments 为 JSON 字符串，LangChain 解析失败会静默丢弃）。
def _extract_tool_calls(message: Any) -> list[dict[str, Any]]:
    calls = getattr(message, "tool_calls", None) or []
    normalized: list[dict[str, Any]] = []
    for item in calls:
        if not isinstance(item, dict):
            continue
        # 注意不能用 or 合并，否则合法的空参数 {} 会被误判为缺失。
        args = item.get("args") if "args" in item else item.get("arguments")
        normalized.append(
            {
                "name": item.get("name"),
                "arguments": args,
                "id": item.get("id"),
            }
        )
    if normalized:
        return normalized
    raw = getattr(message, "additional_kwargs", None) or {}
    for item in raw.get("tool_calls") or []:
        if not isinstance(item, dict):
            continue
        function = item.get("function") or {}
        normalized.append(
            {
                "name": function.get("name") or item.get("name"),
                "arguments": function.get("arguments", item.get("arguments")),
                "id": item.get("id"),
            }
        )
    return normalized


# 调查决策两次校验均失败时抛出的异常。
class InvestigationDecisionError(FlowFixError):
    pass


# 使用 OpenAI 兼容接口生成有界的单 Agent 只读调查决策 JSON。
class LangChainInvestigationDecision:
    # 创建聊天模型、决策提示词、修复提示词与解析链。
    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float,
        native_tools: bool = False,
    ) -> None:
        chat = ChatOpenAI(
            api_key=api_key,
            base_url=base_url,
            model=model,
            temperature=0,
            timeout=timeout_seconds,
            max_retries=1,
        )
        system_prompt = (
            "你是 FlowFix 设备运维调查决策助手。只能从给定的 ToolSpec 列表中选择一个"
            "只读能力调用，不得选择列表之外的能力，不得发起任何写入。每次决策要么输出"
            "一个 tool_call 继续调查，要么输出 conclusion 与 stop_reason 结束调查。"
            "输出必须是一个 JSON 对象，不能包含 JSON 之外的任何文字，"
            "不能输出 markdown 代码块。\n"
            f"继续调查时：{_SCHEMA_DOC}\n结束调查时：{_FINAL_SCHEMA_DOC}"
        )
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", system_prompt),
                (
                    "human",
                    "事故目标：{goal}\n允许能力：{allowed_capabilities}\n"
                    "当前步数/总步数：{step}/{max_steps}\n\n"
                    "可用工具：\n{specs}\n\n既有观测：\n{observations}\n\n"
                    "请输出下一步决策的 JSON。",
                ),
            ]
        )
        repair_prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "修复以下调查决策 JSON。只能从给定工具列表中选择能力，"
                    "不能选择列表之外的能力；要么修正为合法的工具调用，"
                    "要么补全 conclusion 与 stop_reason。",
                ),
                (
                    "human",
                    "事故目标：{goal}\n允许能力：{allowed_capabilities}\n"
                    "当前步数/总步数：{step}/{max_steps}\n\n可用工具：\n{specs}\n\n"
                    "既有观测：\n{observations}\n\n校验错误：{error}\n\n"
                    "原输出：\n{draft}\n\n输出修复后的 JSON。",
                ),
            ]
        )
        parser = StrOutputParser()
        self._chain = prompt | chat | parser
        self._repair_chain = repair_prompt | chat | parser
        self._prompt = prompt
        self._chat = chat
        self._native_tools = native_tools
        # 原生工具链在首次 decide 时按 specs 惰性绑定；测试可直接覆盖此属性。
        self._native_chain: Any | None = None
        self.model = model

    # 根据请求、可用工具清单与既有观测产生下一步只读决策。
    async def decide(
        self,
        request: InvestigationRequest,
        specs: list[ToolSpec],
        observations: list[ToolObservation],
    ) -> AgentDecision:
        variables = self._build_variables(request, specs, observations)
        if self._native_tools:
            return await self._decide_native(request, specs, observations, variables)
        text = await self._chain.ainvoke(variables)
        decision, error = self._parse_and_validate(text, request, specs, observations)
        if decision is not None:
            return decision
        repaired = await self._repair_chain.ainvoke(
            {**variables, "draft": text, "error": error}
        )
        decision, repair_error = self._parse_and_validate(
            repaired, request, specs, observations
        )
        if decision is not None:
            return decision
        raise InvestigationDecisionError(
            f"decision output invalid after repair: {repair_error or error}"
        )

    # 组装每次决策共享的提示词变量。
    def _build_variables(
        self,
        request: InvestigationRequest,
        specs: list[ToolSpec],
        observations: list[ToolObservation],
    ) -> dict[str, str]:
        return {
            "goal": request.goal,
            "allowed_capabilities": "、".join(sorted(request.allowed_capabilities)),
            "specs": self._format_specs(specs),
            "observations": self._format_observations(observations),
            "step": str(len(observations) + 1),
            "max_steps": str(request.max_steps),
        }

    # 原生 function calling 分支：绑定工具 Schema 后调用，响应含 tool_calls 或收尾内容。
    async def _decide_native(
        self,
        request: InvestigationRequest,
        specs: list[ToolSpec],
        observations: list[ToolObservation],
        variables: dict[str, str],
    ) -> AgentDecision:
        if self._native_chain is not None:
            message = await self._native_chain.ainvoke(variables)
        else:
            native_chain = self._prompt | self._chat.bind_tools(
                self._to_openai_tools(specs)
            )
            message = await native_chain.ainvoke(variables)
        decision, error = self._parse_native_message(
            message, request, specs, observations
        )
        if decision is not None:
            return decision
        # 降级修复：复用 text-json 修复链，要求其输出合法决策 JSON。
        repaired = await self._repair_chain.ainvoke(
            {**variables, "draft": self._native_draft(message), "error": error}
        )
        decision, repair_error = self._parse_and_validate(
            repaired, request, specs, observations
        )
        if decision is not None:
            return decision
        raise InvestigationDecisionError(
            f"native decision output invalid after repair: {repair_error or error}"
        )

    # 解析原生工具链返回的消息：优先取第一条 tool_call，否则从 content 解析收尾 JSON。
    def _parse_native_message(
        self,
        message: Any,
        request: InvestigationRequest,
        specs: list[ToolSpec],
        observations: list[ToolObservation],
    ) -> tuple[AgentDecision | None, str | None]:
        tool_calls = _extract_tool_calls(message)
        if tool_calls:
            first = tool_calls[0]
            name = first.get("name")
            if not name:
                return None, "native tool_call missing name"
            raw_args = first.get("arguments")
            if isinstance(raw_args, str):
                try:
                    args = json.loads(raw_args)
                except json.JSONDecodeError as exc:
                    return None, f"invalid tool arguments json: {exc}"
            else:
                args = raw_args
            if not isinstance(args, dict):
                return None, "tool arguments must be a JSON object"
            tool_call = ToolCall(
                capability=name,
                arguments=args,
                call_id=str(first.get("id") or ""),
            )
            validated, error = self._validate_tool_call(
                tool_call, request, specs, observations
            )
            if validated is None:
                return None, error
            return AgentDecision(tool_call=validated), None
        text = _extract_message_text(getattr(message, "content", None))
        if not text:
            return None, "native message has neither tool_calls nor content"
        return self._parse_and_validate(text, request, specs, observations)

    # 把原生消息转成修复链可读的 draft 文本（tool_call 或收尾 JSON）。
    @staticmethod
    def _native_draft(message: Any) -> str:
        tool_calls = _extract_tool_calls(message)
        if tool_calls:
            first = tool_calls[0]
            raw_args = first.get("arguments")
            args = raw_args if isinstance(raw_args, dict) else {}
            return json.dumps(
                {
                    "tool_call": {
                        "capability": first.get("name"),
                        "arguments": args,
                        "call_id": str(first.get("id") or ""),
                    },
                    "conclusion": None,
                    "uncertainty": [],
                    "stop_reason": None,
                },
                ensure_ascii=False,
            )
        return _extract_message_text(getattr(message, "content", None))

    # 将 ToolSpec 清单转换为 OpenAI function calling 的原生工具 Schema。
    @staticmethod
    def _to_openai_tools(specs: list[ToolSpec]) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": spec.input_schema,
                },
            }
            for spec in specs
        ]

    # 校验工具调用能力边界并覆盖确定性调用标识；text-json 与原生分支共用。
    @staticmethod
    def _validate_tool_call(
        tool_call: ToolCall,
        request: InvestigationRequest,
        specs: list[ToolSpec],
        observations: list[ToolObservation],
    ) -> tuple[ToolCall | None, str | None]:
        allowed = {spec.name for spec in specs}
        if tool_call.capability not in request.allowed_capabilities:
            return None, f"capability outside allowed set: {tool_call.capability}"
        if tool_call.capability not in allowed:
            return None, f"capability not in tool list: {tool_call.capability}"
        # 覆盖为确定性调用标识，保证重复决策幂等。
        validated = ToolCall(
            capability=tool_call.capability,
            arguments=tool_call.arguments,
            call_id=f"{request.trace_id}:dec:{len(observations) + 1}",
        )
        return validated, None

    # 解析并校验模型输出：剥围栏、JSON 解析、Schema 校验与工具能力边界。
    @staticmethod
    def _parse_and_validate(
        text: str,
        request: InvestigationRequest,
        specs: list[ToolSpec],
        observations: list[ToolObservation],
    ) -> tuple[AgentDecision | None, str | None]:
        cleaned = strip_code_fence(text)
        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            return None, f"invalid json: {exc}"
        try:
            decision = AgentDecision.model_validate(payload)
        except ValidationError as exc:
            return None, f"schema invalid: {exc}"
        if decision.tool_call is not None:
            validated, error = LangChainInvestigationDecision._validate_tool_call(
                decision.tool_call, request, specs, observations
            )
            if validated is None:
                return None, error
            decision.tool_call = validated
            return decision, None
        if not decision.conclusion and not decision.stop_reason:
            return None, "conclusion or stop_reason required when stopping"
        if (
            decision.stop_reason is not None
            and decision.stop_reason not in _TERMINAL_STOP_REASONS
        ):
            return None, f"invalid stop reason: {decision.stop_reason}"
        return decision, None

    # 将可用工具清单格式化为模型可读取的文本块。
    @staticmethod
    def _format_specs(specs: list[ToolSpec]) -> str:
        blocks = []
        for spec in specs:
            blocks.append(
                f"- {spec.name}（{spec.access.value}）：{spec.description}\n"
                f"  入参：{json.dumps(spec.input_schema, ensure_ascii=False)}"
            )
        return "\n".join(blocks) if blocks else "（无可用工具）"

    # 将既有观测压缩为模型可读取的文本块，失败观测只保留错误摘要。
    @staticmethod
    def _format_observations(observations: list[ToolObservation]) -> str:
        blocks = []
        for item in observations:
            if item.success:
                summary = json.dumps(item.payload, ensure_ascii=False)[:500]
            else:
                summary = f"{item.error_code}: {item.error_message}"
            blocks.append(
                f"- {item.call_id} {item.capability}（{'成功' if item.success else '失败'}）"
                f"：{summary}"
            )
        return "\n".join(blocks) if blocks else "（尚无观测）"
