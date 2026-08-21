from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from flowfix_agent.retrieval.models import Evidence


# 约束答案生成器必须提供的生成、修复和模型标识能力。
class AnswerGeneratorPort(Protocol):
    model: str

    # 根据问题和证据生成带引用的答案。
    async def generate(self, question: str, evidence: Sequence[Evidence]) -> str: ...

    # 修复未通过引用校验的候选答案。
    async def repair(
        self, question: str, evidence: Sequence[Evidence], draft: str
    ) -> str: ...
