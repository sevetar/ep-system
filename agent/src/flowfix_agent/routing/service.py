from __future__ import annotations

import logging
import uuid

from flowfix_agent.routing.models import RouteDecision, RouteType
from flowfix_agent.routing.ports import RouteClassifier
from flowfix_agent.routing.rules import extract_entities, route_by_rules

logger = logging.getLogger(__name__)


# 确定性优先的路由服务；在线异步路径可注入结构化分类器做安全兜底。
class RequestRouter:

    def __init__(self, classifier: RouteClassifier | None = None) -> None:
        self.classifier = classifier

    # 将用户文本路由到四类链路之一并返回路由决策。
    def route(
        self,
        text: str,
        *,
        thread_id: str | None = None,
        trace_id: str | None = None,
        intent_hint: RouteType | None = None,
    ) -> RouteDecision:
        # 未显式传入 trace_id 时自动生成，保证整条链路可追踪。
        effective_trace_id = trace_id or uuid.uuid4().hex
        # 快路径：多轮会话中已确认的意图直接沿用，跳过规则路由；
        # NEEDS_CLARIFICATION 除外，它表示仍需澄清，必须重新走规则判定。
        if intent_hint is not None and intent_hint is not RouteType.NEEDS_CLARIFICATION:
            return RouteDecision(
                route_type=intent_hint,
                confidence=1.0,
                reason_code="CONTINUED_CONFIRMED_INTENT",
                extracted_entities=extract_entities(text),
                thread_id=thread_id,
                trace_id=effective_trace_id,
            )
        # 常规路径：基于确定性规则对文本分类，模型不参与路由。
        return route_by_rules(text, effective_trace_id, thread_id)

    async def route_async(
        self,
        text: str,
        *,
        thread_id: str | None = None,
        trace_id: str | None = None,
        intent_hint: RouteType | None = None,
    ) -> RouteDecision:
        """确定性规则优先，仅在意图不清时调用 LLM；模型故障安全退化为澄清。"""
        decision = self.route(
            text, thread_id=thread_id, trace_id=trace_id, intent_hint=intent_hint
        )
        if (
            decision.route_type is not RouteType.NEEDS_CLARIFICATION
            or self.classifier is None
            or intent_hint is not None
        ):
            return decision
        try:
            return await self.classifier.classify(
                text, trace_id=decision.trace_id, thread_id=thread_id
            )
        except Exception as exc:
            logger.warning("LLM route fallback unavailable: %s", type(exc).__name__)
            return decision.model_copy(update={"reason_code": "LLM_FALLBACK_UNAVAILABLE"})
