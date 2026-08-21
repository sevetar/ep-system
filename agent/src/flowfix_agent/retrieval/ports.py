from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from flowfix_agent.retrieval.models import RetrievalCandidate


# 约束关键词和向量检索适配器必须提供的双路召回能力。
class SearchPort(Protocol):
    # 使用 BM25 和业务过滤条件召回关键词候选。
    async def bm25_search(
        self,
        query: str,
        knowledge_keys: list[str],
        top_k: int,
        tenant_id: str,
        visibility: str,
        device_category: str | None,
        device_model: str | None,
    ) -> list[RetrievalCandidate]: ...

    # 使用查询向量和业务过滤条件召回语义候选。
    async def vector_search(
        self,
        vector: list[float],
        knowledge_keys: list[str],
        top_k: int,
        tenant_id: str,
        visibility: str,
        device_category: str | None,
        device_model: str | None,
    ) -> list[RetrievalCandidate]: ...


# 约束候选重排器必须提供的相关性排序能力。
class RerankerPort(Protocol):
    # 返回每个有效候选下标对应的重排分数。
    async def rerank(
        self,
        query: str,
        candidates: Sequence[RetrievalCandidate],
    ) -> list[tuple[int, float]]: ...
