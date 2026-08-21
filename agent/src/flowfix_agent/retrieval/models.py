from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

from flowfix_agent.core.models import RequestScope
from flowfix_agent.knowledge.models import SourceType


# 枚举支持的关键词、向量和混合检索模式。
class RetrievalMode(StrEnum):
    BM25 = "bm25"
    DENSE = "dense"
    HYBRID = "hybrid"


# 保存召回候选及其在各检索阶段产生的分数和状态。
class RetrievalCandidate(BaseModel):
    chunk_id: str
    source_id: str
    source_type: SourceType
    source_version: str
    title: str
    section_path: str
    content: str
    rank: int = 0
    score: float = 0.0
    retrieval_sources: list[Literal["bm25", "dense", "reranker"]] = Field(
        default_factory=list
    )
    bm25_score: float | None = None
    vector_score: float | None = None
    rrf_score: float | None = None
    rerank_score: float | None = None
    selected: bool = False
    filter_reason: str | None = None


# 表示通过筛选、可注入生成模型并可被引用的证据。
class Evidence(BaseModel):
    citation_id: int
    chunk_id: str
    source_id: str
    source_type: SourceType
    source_version: str
    title: str
    section_path: str
    content: str
    score: float
    estimated_tokens: int


# 封装一次检索的候选、最终证据、降级信息和耗时。
class EvidenceBundle(BaseModel):
    trace_id: str
    original_query: str
    retrieval_query: str
    mode: RetrievalMode
    scope: RequestScope
    candidates: list[RetrievalCandidate]
    selected_evidence: list[Evidence]
    budget_used: int
    sufficient: bool
    fallbacks: list[str] = Field(default_factory=list)
    latency_ms: float


# 定义调用方可覆盖的检索模式、返回数量和重排开关。
class RetrievalOptions(BaseModel):
    mode: RetrievalMode = RetrievalMode.HYBRID
    top_k: int | None = Field(default=None, ge=1, le=30)
    rerank: bool | None = None
