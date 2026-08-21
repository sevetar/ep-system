from __future__ import annotations

import re

from flowfix_agent.routing.models import ExtractedEntities, RouteDecision, RouteType

WORK_ORDER_PATTERN = re.compile(r"(?:工单|work\s*order)[：:#\s-]*([A-Za-z0-9_-]+)", re.I)
DEVICE_PATTERN = re.compile(r"(?:设备|device)[：:#\s-]*([A-Za-z0-9_-]+)", re.I)

DISPATCH_WORDS = ("派单", "派给", "维修员", "assign", "dispatch")
INCIDENT_WORDS = ("故障", "停机", "异常", "报警", "根因", "调查", "incident")
KNOWLEDGE_WORDS = ("文档", "手册", "sop", "怎么说", "如何操作", "规定", "说明")


# 基于关键词与实体规则做确定性优先路由；LLM 兜底由 RequestRouter.route_async 编排。
def route_by_rules(text: str, trace_id: str, thread_id: str | None = None) -> RouteDecision:
    normalized = " ".join(text.strip().split())
    lower = normalized.lower()
    entities = extract_entities(normalized)

    has_dispatch_intent = any(word in lower for word in DISPATCH_WORDS)
    has_incident_intent = any(word in lower for word in INCIDENT_WORDS)

    # “调查故障并给出派单建议”是调查链路，不应被其中的“派单”二字截断为直接写操作。
    # 调查完成后如确有派单建议，仍由 Planning/WritePolicy 转交人工审批。
    if has_dispatch_intent and has_incident_intent and entities.device_id:
        return RouteDecision(
            route_type=RouteType.INCIDENT_INVESTIGATION,
            confidence=0.99,
            reason_code="INCIDENT_WITH_DISPATCH_PROPOSAL",
            extracted_entities=entities,
            thread_id=thread_id,
            trace_id=trace_id,
        )

    if has_dispatch_intent:
        return RouteDecision(
            route_type=RouteType.DIRECT_DISPATCH,
            confidence=0.99,
            reason_code="EXPLICIT_DISPATCH_INTENT",
            extracted_entities=entities,
            thread_id=thread_id,
            trace_id=trace_id,
        )

    if has_incident_intent:
        return RouteDecision(
            route_type=RouteType.INCIDENT_INVESTIGATION,
            confidence=0.95,
            reason_code="INCIDENT_INTENT",
            extracted_entities=entities,
            thread_id=thread_id,
            trace_id=trace_id,
        )

    if any(word in lower for word in KNOWLEDGE_WORDS) or normalized.endswith(("?", "？")):
        return RouteDecision(
            route_type=RouteType.KNOWLEDGE_QA,
            confidence=0.85,
            reason_code="KNOWLEDGE_QUESTION",
            extracted_entities=entities,
            thread_id=thread_id,
            trace_id=trace_id,
        )

    return RouteDecision(
        route_type=RouteType.NEEDS_CLARIFICATION,
        confidence=0.6,
        reason_code="INTENT_UNCLEAR",
        extracted_entities=entities,
        missing_fields=["intent"],
        thread_id=thread_id,
        trace_id=trace_id,
    )


# 返回正则第一次命中的捕获组，未命中时返回 None。
def _first_group(pattern: re.Pattern[str], value: str) -> str | None:
    match = pattern.search(value)
    return match.group(1) if match else None


# 只提取跨链路通用实体，不参与意图分类或业务完整性判定。
def extract_entities(text: str) -> ExtractedEntities:
    normalized = " ".join(text.strip().split())
    return ExtractedEntities(
        work_order_id=_first_group(WORK_ORDER_PATTERN, normalized),
        device_id=_first_group(DEVICE_PATTERN, normalized),
    )
