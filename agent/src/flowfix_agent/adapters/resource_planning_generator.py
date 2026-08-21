from __future__ import annotations

import json
from collections.abc import Sequence

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import ValidationError

from flowfix_agent.adapters.models import format_evidence, strip_code_fence
from flowfix_agent.planning.models import IncidentContext, TaskSpec
from flowfix_agent.planning.workers.resource_planning import (
    ResourcePlanningGenerationError,
    ResourcePlanningResult,
)
from flowfix_agent.retrieval.models import Evidence

# 注意：JSON 示例中的花括号需转义为双花括号，避免被模板解析为占位符。
_SCHEMA_DOC = """\
JSON 结构如下：
{{
  "primary_available": true,
  "confidence": 0.0,
  "candidates": [
    {{
      "candidate_id": "c1",
      "kind": "spare_part",
      "name": "备件名称",
      "description": "候选说明",
      "available": true,
      "supporting_evidence": [1]
    }}
  ],
  "conflicts": [
    {{
      "conflict_id": "cf1",
      "resource_id": "r1",
      "reason": "冲突原因",
      "supporting_evidence": [1]
    }}
  ],
  "alternatives": [
    {{
      "alternative_id": "a1",
      "resource_id": "r1",
      "alternative_name": "替代名称",
      "description": "替代说明",
      "supporting_evidence": [1]
    }}
  ],
  "missing_info": []
}}
"""


# 使用 OpenAI 兼容接口生成受证据约束的结构化资源规划 JSON（只生成 proposal，不占用真实资源）。
class LangChainResourcePlanningGenerator:
    # 创建聊天模型、评估提示词、修复提示词与解析链。
    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float,
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
            "你是 FlowFix 设备运维资源规划助手。只能依据给定证据提出人员、备件与窗口"
            "候选、冲突与替代方案，不得用模型常识补全，更不能占用、预留或写入任何真实"
            "资源。输出必须是一个 JSON 对象，不能包含 JSON 之外的任何文字，不能输出 "
            "markdown 代码块。\n"
            f"{_SCHEMA_DOC}"
            "要求：kind 只能是 personnel/spare_part/window；每条 candidate/conflict/"
            "alternative 必须至少引用一个正证据编号，supporting_evidence 不能为空；"
            "所有引用编号只能来自证据列表中出现的编号；available 表示该候选当前是否"
            "可用，若可用资源缺失则 primary_available 为 false 并给出 conflicts 与 "
            "alternatives；missing_info 列出还需要哪些证据才能确认资源；若证据不足，"
            "primary_available 必须为 false，不得声称资源可用。"
        )
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", system_prompt),
                (
                    "human",
                    "事故目标：{goal}\n资源规划任务：{task}\n\n证据：\n{evidence}\n\n"
                    "请输出资源规划的 JSON。",
                ),
            ]
        )
        repair_prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "修复以下资源规划 JSON。只能保留给定证据支持的内容与引用编号，"
                    "不要添加新事实，不得生成任何占用真实资源的操作。",
                ),
                (
                    "human",
                    "事故目标：{goal}\n资源规划任务：{task}\n\n证据：\n{evidence}\n\n"
                    "校验错误：{error}\n\n原输出：\n{draft}\n\n输出修复后的 JSON。",
                ),
            ]
        )
        parser = StrOutputParser()
        self._chain = prompt | chat | parser
        self._repair_chain = repair_prompt | chat | parser
        self.model = model

    # 根据事故上下文、任务与已筛选证据生成结构化资源规划结果。
    async def generate(
        self,
        incident: IncidentContext,
        task: TaskSpec,
        evidence: Sequence[Evidence],
    ) -> ResourcePlanningResult:
        evidence_text = format_evidence(evidence)
        draft = await self._chain.ainvoke(
            {
                "goal": incident.goal,
                "task": task.description,
                "evidence": evidence_text,
            }
        )
        result, error = self._parse_and_validate(draft, evidence)
        if result is not None:
            return result
        repaired = await self._repair_chain.ainvoke(
            {
                "goal": incident.goal,
                "task": task.description,
                "evidence": evidence_text,
                "draft": draft,
                "error": error,
            }
        )
        result, repair_error = self._parse_and_validate(repaired, evidence)
        if result is not None:
            return result
        raise ResourcePlanningGenerationError(
            f"resource planning output invalid after repair: {repair_error or error}"
        )

    # 解析并校验模型输出：剥围栏、JSON 解析、Schema 校验与引用合法性。
    @staticmethod
    def _parse_and_validate(
        text: str, evidence: Sequence[Evidence]
    ) -> tuple[ResourcePlanningResult | None, str | None]:
        cleaned = strip_code_fence(text)
        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            return None, f"invalid json: {exc}"
        try:
            result = ResourcePlanningResult.model_validate(payload)
        except ValidationError as exc:
            return None, f"schema invalid: {exc}"
        allowed = {item.citation_id for item in evidence}
        sections = {
            "candidate": result.candidates,
            "conflict": result.conflicts,
            "alternative": result.alternatives,
        }
        for section_name, items in sections.items():
            for item in items:
                if not item.supporting_evidence:
                    return None, f"{section_name} lacks supporting evidence"
                invalid = sorted(set(item.supporting_evidence) - allowed)
                if invalid:
                    return None, f"{section_name} cites unknown evidence ids: {invalid}"
        # 主资源不可用时必须同时给出冲突与替代方案，否则结果自相矛盾，触发 repair。
        if not result.primary_available and not (
            result.conflicts or result.alternatives
        ):
            return None, "unavailable resource requires conflicts and alternatives"
        return result, None
