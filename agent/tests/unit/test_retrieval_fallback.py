from flowfix_agent.core.models import RequestScope
from flowfix_agent.knowledge.models import CatalogRecord, SourceType
from flowfix_agent.retrieval.models import RetrievalCandidate
from flowfix_agent.retrieval.selector import EvidenceSelector
from flowfix_agent.retrieval.service import HybridRetrievalService


# 模拟返回单个公共知识版本的目录端口。
class FakeCatalog:
    # 返回固定的激活知识源记录。
    async def list_active(self):
        return [
            CatalogRecord(
                source_id="guide.md",
                source_type=SourceType.PLATFORM_DOC,
                active_version="v1",
                knowledge_key="guide.md:v1",
                content_hash="hash",
                indexed_chunks=1,
                tenant_id="public",
                visibility="public",
            )
        ]


# 模拟 BM25 与向量双路均命中同一分块的搜索端口。
class FakeSearch:
    # 返回固定的 BM25 候选。
    async def bm25_search(self, *args):
        return [_candidate("bm25", bm25_score=3.0)]

    # 返回固定的向量候选。
    async def vector_search(self, *args):
        return [_candidate("dense", vector_score=0.9)]


# 模拟返回固定查询向量的生成器。
class FakeEmbedding:
    # 返回二维查询向量。
    async def embed_query(self, text):
        return [1.0, 0.0]


# 模拟始终超时的重排服务。
class FailingReranker:
    # 抛出超时异常以触发检索降级路径。
    async def rerank(self, query, candidates):
        raise TimeoutError("reranker timeout")


# 模拟无外部副作用的追踪端口。
class FakeTrace:
    # 接收事件但不执行持久化。
    async def emit(self, event_type, trace_id, payload):
        return None


# 构造用于双路融合测试的固定检索候选。
def _candidate(origin, bm25_score=None, vector_score=None):
    return RetrievalCandidate(
        chunk_id="chunk-1",
        source_id="guide.md",
        source_type=SourceType.PLATFORM_DOC,
        source_version="v1",
        title="Guide",
        section_path="Section",
        content="relevant evidence",
        score=bm25_score or vector_score or 0.0,
        retrieval_sources=[origin],
        bm25_score=bm25_score,
        vector_score=vector_score,
    )


# 验证重排失败时保留 RRF 候选并记录降级原因。
async def test_reranker_failure_falls_back_to_rrf_candidates():
    service = HybridRetrievalService(
        FakeSearch(),
        FakeCatalog(),
        FakeEmbedding(),
        EvidenceSelector(100, 3, 0.6, 0.2),
        FakeTrace(),
        FailingReranker(),
        bm25_top_k=10,
        vector_top_k=10,
        rrf_k=60,
        rerank_enabled=True,
    )

    bundle = await service.retrieve("question", RequestScope())

    assert len(bundle.selected_evidence) == 1
    assert bundle.candidates[0].retrieval_sources == ["bm25", "dense"]
    assert bundle.fallbacks == ["reranker_failed:TimeoutError"]
