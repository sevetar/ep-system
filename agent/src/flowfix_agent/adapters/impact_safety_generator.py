from __future__ import annotations

import json
from collections.abc import Sequence

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import ValidationError

from flowfix_agent.adapters.models import format_evidence, strip_code_fence
from flowfix_agent.planning.models import IncidentContext, TaskSpec
from flowfix_agent.planning.workers.impact_safety import (
    RISK_ORDER,
    ImpactSafetyGenerationError,
    ImpactSafetyResult,
)
from flowfix_agent.retrieval.models import Evidence

# 注意：JSON 示例中的花括号需转义为双花括号，避免被模板解析为占位符。
_SCHEMA_DOC = """\
JSON 结构如下：
{{
  "overall_risk_level": "high",
  "confidence": 0.0,
  "impact_scopes": [
    {{
      "scope_id": "s1",
      "target": "受影响目标",
      "description": "影响描述",
      "supporting_evidence": [1]
    }}
  ],
  "risks": [
    {{
      "risk_id": "r1",
      "title": "风险标题",
      "description": "风险说明",
      "severity": "high",
      "supporting_evidence": [1]
    }}
  ],
  "safety_constraints": [
    {{
      "constraint_id": "c1",
      "action": "处置必须遵守的操作边界",
      "rationale": "理由",
      "supporting_evidence": [1]
    }}
  ],
  "mandatory_checks": [
    {{
      "check_id": "m1",
      "item": "处置前必选校验项",
      "supporting_evidence": [1]
    }}
  ],
  "missing_info": []
}}
"""


# 使用 OpenAI 兼容接口生成受证据约束的结构化影响与安全评估 JSON。
class LangChainImpactSafetyGenerator:
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
            "你是 FlowFix 设备运维影响与安全评估助手。只能依据给定证据判断影响范围、"
            "风险等级、安全约束与必选校验，不得用模型常识补全，更不能把风险等级降级。"
            "输出必须是一个 JSON 对象，不能包含 JSON 之外的任何文字，不能输出 "
            "markdown 代码块。\n"
            f"{_SCHEMA_DOC}"
            "要求：overall_risk_level 只能是 unknown/low/medium/high/critical，且"
            "不得低于任一 risk 的 severity；confidence 是 0 到 1 之间的数字；"
            "每条 impact_scope/risk/safety_constraint/mandatory_check 必须至少引用"
            "一个正证据编号，supporting_evidence 不能为空；所有引用编号只能来自证据"
            "列表中出现的编号；missing_info 列出还需要哪些证据才能确认评估结果；"
            "若证据不足，overall_risk_level 必须为 unknown，不得声称风险低。"
        )
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", system_prompt),
                (
                    "human",
                    "事故目标：{goal}\n评估任务：{task}\n\n证据：\n{evidence}\n\n"
                    "请输出影响与安全评估的 JSON。",
                ),
            ]
        )
        repair_prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "修复以下影响与安全评估 JSON。只能保留给定证据支持的内容与引用编号，"
                    "不要添加新事实，不得降低风险等级。",
                ),
                (
                    "human",
                    "事故目标：{goal}\n评估任务：{task}\n\n证据：\n{evidence}\n\n"
                    "校验错误：{error}\n\n原输出：\n{draft}\n\n输出修复后的 JSON。",
                ),
            ]
        )
        parser = StrOutputParser()
        self._chain = prompt | chat | parser
        self._repair_chain = repair_prompt | chat | parser
        self.model = model

    # 根据事故上下文、任务与已筛选证据生成结构化影响与安全评估结果。
    async def generate(
        self,
        incident: IncidentContext,
        task: TaskSpec,
        evidence: Sequence[Evidence],
    ) -> ImpactSafetyResult:
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
        raise ImpactSafetyGenerationError(
            f"impact safety output invalid after repair: {repair_error or error}"
        )

    # 解析并校验模型输出：剥围栏、JSON 解析、Schema 校验、引用合法与风险守恒。
    @staticmethod
    def _parse_and_validate(
        text: str, evidence: Sequence[Evidence]
    ) -> tuple[ImpactSafetyResult | None, str | None]:
        cleaned = strip_code_fence(text)
        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            return None, f"invalid json: {exc}"
        try:
            result = ImpactSafetyResult.model_validate(payload)
        except ValidationError as exc:
            return None, f"schema invalid: {exc}"
        allowed = {item.citation_id for item in evidence}
        sections = {
            "impact_scope": result.impact_scopes,
            "risk": result.risks,
            "safety_constraint": result.safety_constraints,
            "mandatory_check": result.mandatory_checks,
        }
        for section_name, items in sections.items():
            for item in items:
                if not item.supporting_evidence:
                    return (
                        None,
                        f"{section_name} {getattr(item, f'{section_name}_id', item.item)} "
                        "lacks supporting evidence",
                    )
                invalid = sorted(set(item.supporting_evidence) - allowed)
                if invalid:
                    return None, f"{section_name} cites unknown evidence ids: {invalid}"
        # 风险守恒：整体等级不能低于已识别风险的最高等级，防止模型擅自降风险。
        max_severity = max(
            (RISK_ORDER[risk.severity] for risk in result.risks), default=0
        )
        if RISK_ORDER[result.overall_risk_level] < max_severity:
            return None, "overall risk level must not be lower than the highest identified risk"
        return result, None
