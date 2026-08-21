import pytest

from flowfix_agent.knowledge.models import SourceType
from flowfix_agent.retrieval.fusion import reciprocal_rank_fusion
from flowfix_agent.retrieval.models import RetrievalCandidate


# 构造带指定来源和分数的融合测试候选。
def candidate(chunk_id: str, origin: str, score: float) -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk_id=chunk_id,
        source_id="guide.md",
        source_type=SourceType.PLATFORM_DOC,
        source_version="v1",
        title="Guide",
        section_path="Section",
        content=chunk_id,
        retrieval_sources=[origin],
        bm25_score=score if origin == "bm25" else None,
        vector_score=score if origin == "dense" else None,
    )


# 验证 RRF 会提高被两路检索共同命中文档的排名。
def test_rrf_rewards_documents_found_by_both_retrievers():
    bm25 = [candidate("a", "bm25", 20), candidate("b", "bm25", 10)]
    dense = [candidate("b", "dense", 0.9), candidate("c", "dense", 0.8)]

    fused = reciprocal_rank_fusion([bm25, dense], rank_constant=60)

    assert fused[0].chunk_id == "b"
    assert set(fused[0].retrieval_sources) == {"bm25", "dense"}
    assert fused[0].bm25_score == 10
    assert fused[0].vector_score == pytest.approx(0.9)
    assert [item.rank for item in fused] == [1, 2, 3]
