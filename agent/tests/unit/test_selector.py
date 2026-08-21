from flowfix_agent.knowledge.models import SourceType
from flowfix_agent.retrieval.models import RetrievalCandidate
from flowfix_agent.retrieval.selector import EvidenceSelector


# 构造具有指定阶段分数的测试检索候选。
def make_candidate(
    chunk_id: str,
    content: str,
    *,
    bm25_score: float | None = None,
    vector_score: float | None = None,
    rerank_score: float | None = None,
) -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk_id=chunk_id,
        source_id="guide.md",
        source_type=SourceType.PLATFORM_DOC,
        source_version="v1",
        title="Guide",
        section_path="Section",
        content=content,
        score=bm25_score or vector_score or 0,
        retrieval_sources=["bm25" if bm25_score is not None else "dense"],
        bm25_score=bm25_score,
        vector_score=vector_score,
        rerank_score=rerank_score,
    )


# 验证筛选器过滤低分向量候选和重复内容。
def test_selector_filters_low_dense_scores_and_duplicates():
    selector = EvidenceSelector(
        token_budget=100,
        final_top_k=3,
        vector_min_score=0.6,
        rerank_min_score=0.2,
    )
    candidates = [
        make_candidate("a", "有效证据", bm25_score=2),
        make_candidate("b", "有效证据", vector_score=0.9),
        make_candidate("c", "无关证据", vector_score=0.5),
    ]

    selected, used = selector.select(candidates)

    assert [item.chunk_id for item in selected] == ["a"]
    assert used == len("有效证据")
    assert candidates[1].filter_reason == "duplicate_content"
    assert candidates[2].filter_reason == "below_relevance_threshold"


# 验证证据内容超过预算时不会被选中。
def test_selector_enforces_evidence_budget():
    selector = EvidenceSelector(
        token_budget=5,
        final_top_k=3,
        vector_min_score=0.6,
        rerank_min_score=0.2,
    )
    candidates = [make_candidate("a", "超过预算的证据", bm25_score=2)]

    selected, used = selector.select(candidates)

    assert selected == []
    assert used == 0
    assert candidates[0].filter_reason == "evidence_budget"


# 验证存在重排分数时由重排阈值决定最终相关性。
def test_rerank_score_controls_relevance_after_hybrid_recall():
    selector = EvidenceSelector(
        token_budget=100,
        final_top_k=3,
        vector_min_score=0.6,
        rerank_min_score=0.2,
    )
    candidates = [
        make_candidate("a", "词法命中但语义无关", bm25_score=4.2, rerank_score=0.01),
        make_candidate("b", "重排确认相关", bm25_score=1.1, rerank_score=0.85),
    ]

    selected, _ = selector.select(candidates)

    assert [item.chunk_id for item in selected] == ["b"]
    assert candidates[0].filter_reason == "below_relevance_threshold"
