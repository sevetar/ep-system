from __future__ import annotations

from typing import Protocol

from flowfix_agent.routing.models import RouteDecision


class RouteClassifier(Protocol):
    """只负责意图分类；不执行链路，也不决定业务必填字段。"""

    async def classify(
        self, text: str, *, trace_id: str, thread_id: str | None = None
    ) -> RouteDecision: ...
