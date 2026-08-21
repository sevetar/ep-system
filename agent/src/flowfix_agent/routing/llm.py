from __future__ import annotations

import json

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field, ValidationError

from flowfix_agent.adapters.models import strip_code_fence
from flowfix_agent.routing.models import RouteDecision, RouteType
from flowfix_agent.routing.rules import extract_entities


class _Classification(BaseModel):
    route_type: RouteType
    confidence: float = Field(ge=0, le=1)
    reason_code: str = Field(min_length=1, max_length=80)


class LLMRouteClassifier:
    """OpenAI 兼容的结构化分类兜底；输出仍由本地 Schema 与实体提取约束。"""

    def __init__(self, api_key: str, base_url: str, model: str, timeout_seconds: float) -> None:
        chat = ChatOpenAI(
            api_key=api_key,
            base_url=base_url,
            model=model,
            temperature=0,
            timeout=timeout_seconds,
            max_retries=1,
        )
        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "你是 FlowFix 请求意图分类器。只允许输出一个 JSON 对象，字段为 "
                    "route_type、confidence、reason_code。route_type 只能是 KNOWLEDGE_QA、"
                    "DIRECT_DISPATCH、INCIDENT_INVESTIGATION、NEEDS_CLARIFICATION。"
                    "知识解释或操作咨询归 KNOWLEDGE_QA；明确要求派人或派单归 DIRECT_DISPATCH；"
                    "针对具体异常的根因、影响或处置调查归 INCIDENT_INVESTIGATION；信息不足才"
                    "归 NEEDS_CLARIFICATION。你只能分类，不能执行工具或补造实体。",
                ),
                ("human", "待分类消息：{message}"),
            ]
        )
        self._chain = prompt | chat | StrOutputParser()

    async def classify(
        self, text: str, *, trace_id: str, thread_id: str | None = None
    ) -> RouteDecision:
        raw = await self._chain.ainvoke({"message": text})
        try:
            parsed = _Classification.model_validate(json.loads(strip_code_fence(raw)))
        except (json.JSONDecodeError, ValidationError) as exc:
            raise ValueError("LLM router returned an invalid classification") from exc
        missing = ["intent"] if parsed.route_type is RouteType.NEEDS_CLARIFICATION else []
        return RouteDecision(
            route_type=parsed.route_type,
            confidence=parsed.confidence,
            reason_code=f"LLM_{parsed.reason_code.upper()}",
            extracted_entities=extract_entities(text),
            missing_fields=missing,
            thread_id=thread_id,
            trace_id=trace_id,
        )
