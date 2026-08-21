from __future__ import annotations

import json
from collections.abc import Sequence

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import ValidationError

from flowfix_agent.adapters.models import format_evidence, strip_code_fence
from flowfix_agent.planning.models import IncidentContext, TaskSpec
from flowfix_agent.planning.workers.diagnosis import (
    DiagnosisGenerationError,
    DiagnosisResult,
)
from flowfix_agent.retrieval.models import Evidence

# 注意：JSON 示例中的花括号需转义为双花括号，避免被模板解析为占位符。
_SCHEMA_DOC = """\
JSON 结构如下：
{{
  "conclusion": "总结论",
  "confidence": 0.0,
  "hypotheses": [
    {{
      "hypothesis_id": "h1",
      "title": "假设标题",
      "summary": "假设说明",
      "supporting_evidence": [1],
      "opposing_evidence": [],
      "confidence": 0.0,
      "missing_info": []
    }}
  ],
  "missing_info": [],
  "hypothesis_revised": null,
  "conflict": null
}}
"""


# 使用 OpenAI 兼容接口生成受证据约束的结构化根因诊断 JSON。
class LangChainDiagnosisGenerator:
    # 创建聊天模型、诊断提示词、修复提示词与解析链。
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
            "你是 FlowFix 设备运维根因诊断助手。只能依据给定证据判断根因，"
            "不得用模型常识补全。输出必须是一个 JSON 对象，不能包含 JSON 之外的"
            "任何文字，不能输出 markdown 代码块。\n"
            f"{_SCHEMA_DOC}"
            "要求：confidence 是 0 到 1 之间的数字；每条假设必须至少引用一个正证据"
            "编号，supporting_evidence 不能为空；supporting_evidence 和 "
            "opposing_evidence 只能引用证据列表中出现的编号；missing_info 列出还需要"
            "哪些证据才能确认假设；若证据相互矛盾，明确哪条更可信并给出理由。"
            "若新证据推翻了先前根因假设，必须填写 hypothesis_revised 说明修订原因；"
            "若诊断结论与已给出的影响评估结论相悖，必须填写 conflict 说明冲突。"
            "未发生上述情况时，hypothesis_revised 与 conflict 必须为 null。"
        )
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", system_prompt),
                (
                    "human",
                    "事故目标：{goal}\n诊断任务：{task}\n\n证据：\n{evidence}\n\n"
                    "请输出根因诊断的 JSON。",
                ),
            ]
        )
        repair_prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "修复以下诊断 JSON。只能保留给定证据支持的内容与引用编号，"
                    "不要添加新事实。",
                ),
                (
                    "human",
                    "事故目标：{goal}\n诊断任务：{task}\n\n证据：\n{evidence}\n\n"
                    "校验错误：{error}\n\n原输出：\n{draft}\n\n输出修复后的 JSON。",
                ),
            ]
        )
        parser = StrOutputParser()
        self._chain = prompt | chat | parser
        self._repair_chain = repair_prompt | chat | parser
        self.model = model

    # 根据事故上下文、任务与已筛选证据生成结构化诊断结果。
    async def generate(
        self,
        incident: IncidentContext,
        task: TaskSpec,
        evidence: Sequence[Evidence],
    ) -> DiagnosisResult:
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
        raise DiagnosisGenerationError(
            f"diagnosis output invalid after repair: {repair_error or error}"
        )

    # 解析并校验模型输出：剥围栏、JSON 解析、Schema 校验与引用合法性。
    @staticmethod
    def _parse_and_validate(
        text: str, evidence: Sequence[Evidence]
    ) -> tuple[DiagnosisResult | None, str | None]:
        cleaned = strip_code_fence(text)
        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            return None, f"invalid json: {exc}"
        try:
            result = DiagnosisResult.model_validate(payload)
        except ValidationError as exc:
            return None, f"schema invalid: {exc}"
        allowed = {item.citation_id for item in evidence}
        for hypothesis in result.hypotheses:
            if not hypothesis.supporting_evidence:
                return (
                    None,
                    f"hypothesis {hypothesis.hypothesis_id} lacks supporting evidence",
                )
            cited = set(hypothesis.supporting_evidence) | set(
                hypothesis.opposing_evidence
            )
            invalid = sorted(cited - allowed)
            if invalid:
                return None, f"unknown evidence ids: {invalid}"
        return result, None
