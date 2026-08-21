import httpx

from flowfix_agent.adapters.models import (
    OpenAICompatibleEmbeddings,
    OpenAICompatibleReranker,
)
from flowfix_agent.knowledge.models import SourceType
from flowfix_agent.retrieval.models import RetrievalCandidate


# 验证向量适配器会按服务端 index 恢复输入顺序。
async def test_embedding_adapter_preserves_provider_index_order():
    # 模拟返回顺序与输入顺序不同的 Embedding 接口。
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/embeddings")
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 1, "embedding": [0.0, 1.0]},
                    {"index": 0, "embedding": [1.0, 0.0]},
                ]
            },
        )

    async with httpx.AsyncClient(
        base_url="https://provider.example/v1/",
        transport=httpx.MockTransport(handler),
    ) as client:
        adapter = OpenAICompatibleEmbeddings(client, "embedding-model", dimensions=2)
        vectors = await adapter.embed_documents(["first", "second"])

    assert vectors == [[1.0, 0.0], [0.0, 1.0]]


# 验证重排适配器返回候选下标和相关性分数组合。
async def test_reranker_adapter_returns_index_score_pairs():
    # 模拟返回两个候选重排结果的远程接口。
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/rerank")
        return httpx.Response(
            200,
            json={
                "results": [
                    {"index": 1, "relevance_score": 0.9},
                    {"index": 0, "relevance_score": 0.2},
                ]
            },
        )

    candidates = [
        RetrievalCandidate(
            chunk_id=str(index),
            source_id="guide.md",
            source_type=SourceType.PLATFORM_DOC,
            source_version="v1",
            title="Guide",
            section_path="",
            content=f"content-{index}",
        )
        for index in range(2)
    ]
    async with httpx.AsyncClient(
        base_url="https://provider.example/v1/",
        transport=httpx.MockTransport(handler),
    ) as client:
        adapter = OpenAICompatibleReranker(client, "rerank-model")
        ranking = await adapter.rerank("query", candidates)

    assert ranking == [(1, 0.9), (0, 0.2)]
