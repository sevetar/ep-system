from flowfix_agent.core.models import RequestScope
from flowfix_agent.evaluation.qa import (
    FILTER_REASON_KEYS,
    _summarize_filter_stats,
    run_l2_evaluation,
)
from flowfix_agent.knowledge.models import SourceType
from flowfix_agent.retrieval.models import (
    EvidenceBundle,
    RetrievalCandidate,
    RetrievalMode,
)


# 构造带指定过滤原因的测试检索候选。
def make_candidate(
    chunk_id: str,
    filter_reason: str | None,
    *,
    source_id: str = "guide.md",
) -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk_id=chunk_id,
        source_id=source_id,
        source_type=SourceType.PLATFORM_DOC,
        source_version="v1",
        title="Guide",
        section_path="Section",
        content="有效证据",
        selected=filter_reason is None,
        filter_reason=filter_reason,
    )


# 构造覆盖全部过滤原因的检索结果包。
def make_bundle(
    mode: RetrievalMode,
    candidates: list[RetrievalCandidate],
    budget_used: int,
) -> EvidenceBundle:
    return EvidenceBundle(
        trace_id="trace-1",
        original_query="q",
        retrieval_query="q",
        mode=mode,
        scope=RequestScope(),
        candidates=candidates,
        selected_evidence=[],
        budget_used=budget_used,
        sufficient=True,
        latency_ms=10.0,
    )


# 构造 run_l2_evaluation 所需的轻量容器替身，仅实现被调用的接口。
class _FakeSettings:
    elasticsearch_index = "flowfix-knowledge-v1"
    chat_model = "fake-chat"
    embedding_model = "fake-embedding"
    embedding_dimensions = 3
    rerank_model = "fake-rerank"
    bm25_top_k = 10
    vector_top_k = 10
    final_top_k = 5
    rrf_k = 60
    vector_min_score = 0.6
    rerank_min_score = 0.2
    evidence_token_budget = 3000


class _FakeCatalog:
    async def list_active(self) -> list:
        return []


class _FakeRetrieval:
    def __init__(
        self, bundles: dict[tuple[RetrievalMode, bool], EvidenceBundle]
    ) -> None:
        self._bundles = bundles

    async def retrieve(self, query, scope, options) -> EvidenceBundle:
        return self._bundles[(options.mode, options.rerank)]


class _FakeContainer:
    def __init__(
        self, bundles: dict[tuple[RetrievalMode, bool], EvidenceBundle]
    ) -> None:
        self.retrieval = _FakeRetrieval(bundles)
        self.catalog = _FakeCatalog()
        self.settings = _FakeSettings()


# 验证聚合函数正确累计各过滤原因计数与预算消耗分位数。
def test_summarize_filter_stats_counts_reasons_and_budgets():
    rows = [
        {
            "filter_reasons": [None, "top_k_limit", "duplicate_content"],
            "budget_used": 100,
        },
        {
            "filter_reasons": [
                "below_relevance_threshold",
                "evidence_budget",
                None,
                None,
            ],
            "budget_used": 200,
        },
    ]

    stats = _summarize_filter_stats(rows)

    assert stats == {
        "total_candidates": 7,
        "selected": 3,
        "top_k_limit": 1,
        "duplicate_content": 1,
        "below_relevance_threshold": 1,
        "evidence_budget": 1,
        "budget_used_avg": 150.0,
        "budget_used_p50": 150.0,
        "budget_used_p95": 195.0,
    }


# 验证缺失的过滤原因键会被置零补齐，保证 filter_stats 键齐全。
def test_summarize_filter_stats_zero_fills_missing_reasons():
    rows = [
        {"filter_reasons": [None, None], "budget_used": 42},
        {"filter_reasons": ["top_k_limit"], "budget_used": 58},
    ]

    stats = _summarize_filter_stats(rows)

    assert stats["total_candidates"] == 3
    assert stats["selected"] == 2
    assert stats["top_k_limit"] == 1
    assert stats["duplicate_content"] == 0
    assert stats["below_relevance_threshold"] == 0
    assert stats["evidence_budget"] == 0
    # 键顺序固定为：总数、选中、四个过滤原因、三个预算分位数。
    assert list(stats) == [
        "total_candidates",
        "selected",
        *FILTER_REASON_KEYS,
        "budget_used_avg",
        "budget_used_p50",
        "budget_used_p95",
    ]


# 验证 run_l2_evaluation 为每个检索配置输出 filter_stats，且计入全部 case。
async def test_run_l2_evaluation_includes_filter_stats(tmp_path):
    dataset = tmp_path / "l2.jsonl"
    dataset.write_text(
        '{"case_id":"case-1","query":"q1","relevant_sources":["guide.md"],'
        '"answerable":true,"slice":"single_document"}\n'
        '{"case_id":"case-2","query":"q2","relevant_sources":["guide.md"],'
        '"answerable":true,"slice":"single_document"}\n'
        '{"case_id":"case-3","query":"q3","answerable":false,"slice":"unanswerable"}\n',
        encoding="utf-8",
    )
    bundles = {
        (RetrievalMode.BM25, False): make_bundle(
            RetrievalMode.BM25,
            [
                make_candidate("a", None),
                make_candidate("b", "top_k_limit"),
                make_candidate("c", "duplicate_content"),
                make_candidate("d", "below_relevance_threshold"),
                make_candidate("e", "evidence_budget"),
            ],
            500,
        ),
        (RetrievalMode.DENSE, False): make_bundle(
            RetrievalMode.DENSE,
            [
                make_candidate("a", None),
                make_candidate("b", None),
                make_candidate("c", "top_k_limit"),
            ],
            700,
        ),
        (RetrievalMode.HYBRID, False): make_bundle(
            RetrievalMode.HYBRID,
            [make_candidate("a", None), make_candidate("b", None)],
            800,
        ),
        (RetrievalMode.HYBRID, True): make_bundle(
            RetrievalMode.HYBRID,
            [
                make_candidate("a", None),
                make_candidate("b", "duplicate_content"),
                make_candidate("c", "evidence_budget"),
            ],
            1200,
        ),
    }
    container = _FakeContainer(bundles)

    report = await run_l2_evaluation(container, dataset, include_qa=False)

    retrieval = report["retrieval"]
    assert set(retrieval) == {"bm25", "dense", "hybrid", "hybrid_rerank"}
    # 三个 case 各走一次检索，候选数按 case 数累乘；unanswerable 也计入。
    assert retrieval["bm25"]["filter_stats"] == {
        "total_candidates": 15,
        "selected": 3,
        "top_k_limit": 3,
        "duplicate_content": 3,
        "below_relevance_threshold": 3,
        "evidence_budget": 3,
        "budget_used_avg": 500.0,
        "budget_used_p50": 500,
        "budget_used_p95": 500.0,
    }
    assert retrieval["dense"]["filter_stats"] == {
        "total_candidates": 9,
        "selected": 6,
        "top_k_limit": 3,
        "duplicate_content": 0,
        "below_relevance_threshold": 0,
        "evidence_budget": 0,
        "budget_used_avg": 700.0,
        "budget_used_p50": 700,
        "budget_used_p95": 700.0,
    }
    assert retrieval["hybrid"]["filter_stats"]["total_candidates"] == 6
    assert retrieval["hybrid"]["filter_stats"]["selected"] == 6
    assert retrieval["hybrid_rerank"]["filter_stats"]["total_candidates"] == 9
    assert retrieval["hybrid_rerank"]["filter_stats"]["selected"] == 3
    assert retrieval["hybrid_rerank"]["filter_stats"]["duplicate_content"] == 3
    assert retrieval["hybrid_rerank"]["filter_stats"]["evidence_budget"] == 3
    # 既有报告字段语义保持不变。
    assert retrieval["bm25"]["cases"] == 3
    assert retrieval["bm25"]["answerable_cases"] == 2
    assert retrieval["bm25"]["unanswerable_cases"] == 1
    assert retrieval["bm25"]["hit_rate"] == 1.0
