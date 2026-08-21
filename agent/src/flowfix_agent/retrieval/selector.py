from __future__ import annotations

from flowfix_agent.retrieval.models import Evidence, RetrievalCandidate


# 根据相关性、重复内容和上下文预算筛选最终证据。
class EvidenceSelector:
    # 初始化证据预算、数量上限以及向量和重排分数阈值。
    def __init__(
        self,
        token_budget: int,
        final_top_k: int,
        vector_min_score: float,
        rerank_min_score: float,
    ) -> None:
        self.token_budget = token_budget
        self.final_top_k = final_top_k
        self.vector_min_score = vector_min_score
        self.rerank_min_score = rerank_min_score

    # 按候选顺序执行去重、阈值、数量和预算过滤。
    def select(
        self,
        candidates: list[RetrievalCandidate],
        top_k: int | None = None,
    ) -> tuple[list[Evidence], int]:
        limit = top_k or self.final_top_k
        selected: list[Evidence] = []
        used = 0
        seen_content: set[str] = set()

        for candidate in candidates:
            if len(selected) >= limit:
                candidate.filter_reason = "top_k_limit"
                continue
            normalized = "".join(candidate.content.split()).lower()
            if normalized in seen_content:
                candidate.filter_reason = "duplicate_content"
                continue
            if not self._passes_relevance(candidate):
                candidate.filter_reason = "below_relevance_threshold"
                continue
            estimated_tokens = max(1, len(candidate.content))
            if used + estimated_tokens > self.token_budget:
                candidate.filter_reason = "evidence_budget"
                continue
            candidate.selected = True
            candidate.filter_reason = None
            seen_content.add(normalized)
            used += estimated_tokens
            selected.append(
                Evidence(
                    citation_id=len(selected) + 1,
                    chunk_id=candidate.chunk_id,
                    source_id=candidate.source_id,
                    source_type=candidate.source_type,
                    source_version=candidate.source_version,
                    title=candidate.title,
                    section_path=candidate.section_path,
                    content=candidate.content,
                    score=candidate.score,
                    estimated_tokens=estimated_tokens,
                )
            )
        return selected, used

    # 按 rerank → BM25 → 向量的优先级判断候选是否通过相关性门槛。
    def _passes_relevance(self, candidate: RetrievalCandidate) -> bool:
        if candidate.rerank_score is not None:
            return candidate.rerank_score >= self.rerank_min_score
        if candidate.bm25_score is not None:
            return True
        return (
            candidate.vector_score is not None
            and candidate.vector_score >= self.vector_min_score
        )
