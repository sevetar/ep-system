import os
import uuid

import pytest
from elasticsearch import AsyncElasticsearch

from flowfix_agent.adapters.elasticsearch import ElasticsearchKnowledgeAdapter
from flowfix_agent.knowledge.models import KnowledgeChunk, SourceType


# 验证真实 Elasticsearch 适配器可以建索引、写入并完成双路召回。
@pytest.mark.integration
async def test_elasticsearch_indexes_and_searches_chunks():
    url = os.getenv("ELASTICSEARCH_TEST_URL")
    if not url:
        pytest.skip("set ELASTICSEARCH_TEST_URL to run the component test")

    index_name = f"flowfix-component-{uuid.uuid4().hex}"
    client = AsyncElasticsearch(url)
    adapter = ElasticsearchKnowledgeAdapter(client, index_name, dimensions=8)
    try:
        await adapter.ensure_index()
        chunk = KnowledgeChunk(
            chunk_id="chunk-1",
            source_id="guide.md",
            source_type=SourceType.PLATFORM_DOC,
            source_version="v1",
            knowledge_key="guide.md:v1",
            tenant_id="public",
            visibility="public",
            title="抢单并发控制",
            section_path="工单 / 锁",
            content="同一工单抢单时必须校验数据库状态，避免旧对象覆盖新状态。",
            content_hash="hash-1",
            position=0,
            embedding=[1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        )

        assert await adapter.index_chunks([chunk]) == 1
        assert await adapter.count_knowledge_key("guide.md:v1") == 1

        bm25 = await adapter.bm25_search(
            "工单抢单状态",
            ["guide.md:v1"],
            5,
            "public",
            "public",
            None,
            None,
        )
        dense = await adapter.vector_search(
            [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            ["guide.md:v1"],
            5,
            "public",
            "public",
            None,
            None,
        )

        assert [item.chunk_id for item in bm25] == ["chunk-1"]
        assert [item.chunk_id for item in dense] == ["chunk-1"]
    finally:
        if await client.indices.exists(index=index_name):
            await client.indices.delete(index=index_name)
        await client.close()
