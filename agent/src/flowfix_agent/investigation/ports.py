from __future__ import annotations

from typing import Protocol

from flowfix_agent.investigation.models import (
    AgentDecision,
    InvestigationRequest,
)
from flowfix_agent.tools.models import ToolObservation, ToolSpec


# 调查决策端口：根据请求、能力清单与既有观测产生下一步决策。
class InvestigationDecisionPort(Protocol):
    async def decide(
        self,
        request: InvestigationRequest,
        specs: list[ToolSpec],
        observations: list[ToolObservation],
    ) -> AgentDecision: ...
