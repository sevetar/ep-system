from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from elasticsearch import AsyncElasticsearch, helpers

from flowfix_agent.knowledge.models import KnowledgeChunk, SourceType
from flowfix_agent.retrieval.models import RetrievalCandidate


# 封装知识分块在 Elasticsearch 中的建索引、写入和双路召回操作。
class ElasticsearchKnowledgeAdapter:
    # 保存异步客户端、索引名称和向量维度配置。
    def __init__(
        self,
        client: AsyncElasticsearch,
        index_name: str,
        dimensions: int,
    ) -> None:
        self.client = client
        self.index_name = index_name
        self.dimensions = dimensions

    # 确保知识索引存在，并在需要时重建或校验向量维度。
    async def ensure_index(self, recreate: bool = False) -> None:
        exists = bool(await self.client.indices.exists(index=self.index_name))
        if exists and recreate:
            await self.client.indices.delete(index=self.index_name)
            exists = False
        if exists:
            mapping = await self.client.indices.get_mapping(index=self.index_name)
            actual = mapping[self.index_name]["mappings"]["properties"]["embedding"].get(
                "dims"
            )
            if actual != self.dimensions:
                raise ValueError(
                    f"Index embedding dimensions={actual}, configured={self.dimensions}; "
                    "recreate the index"
                )
            return

        await self.client.indices.create(
            index=self.index_name,
            settings={
                "number_of_shards": 1,
                "number_of_replicas": 0,
                "analysis": {
                    "analyzer": {
                        "flowfix_cjk": {
                            "type": "custom",
                            "tokenizer": "standard",
                            "filter": ["lowercase", "cjk_width", "cjk_bigram"],
                        }
                    }
                },
            },
            mappings={
                "dynamic": "strict",
                "properties": {
                    "chunk_id": {"type": "keyword"},
                    "source_id": {"type": "keyword"},
                    "source_type": {"type": "keyword"},
                    "source_version": {"type": "keyword"},
                    "knowledge_key": {"type": "keyword"},
                    "tenant_id": {"type": "keyword"},
                    "visibility": {"type": "keyword"},
                    "title": {
                        "type": "text",
                        "analyzer": "flowfix_cjk",
                        "fields": {"keyword": {"type": "keyword"}},
                    },
                    "section_path": {"type": "text", "analyzer": "flowfix_cjk"},
                    "content": {"type": "text", "analyzer": "flowfix_cjk"},
                    "content_hash": {"type": "keyword"},
                    "position": {"type": "integer"},
                    "device_category": {"type": "keyword"},
                    "device_model": {"type": "keyword"},
                    "metadata": {"type": "flattened"},
                    "embedding": {
                        "type": "dense_vector",
                        "dims": self.dimensions,
                        "index": True,
                        "similarity": "cosine",
                    },
                },
            },
        )

    # 批量写入知识分块并等待刷新后返回成功数量。
    async def index_chunks(self, chunks: Sequence[KnowledgeChunk]) -> int:
        actions = []
        for chunk in chunks:
            source = chunk.model_dump(mode="json")
            source["source_type"] = chunk.source_type.value
            source["device_category"] = chunk.metadata.get("device_category")
            source["device_model"] = chunk.metadata.get("device_model")
            actions.append(
                {
                    "_op_type": "index",
                    "_index": self.index_name,
                    "_id": chunk.chunk_id,
                    "_source": source,
                }
            )
        success, _ = await helpers.async_bulk(
            self.client,
            actions,
            refresh="wait_for",
            raise_on_error=True,
        )
        return int(success)

    # 统计指定知识版本键对应的已索引分块数量。
    async def count_knowledge_key(self, knowledge_key: str) -> int:
        response = await self.client.count(
            index=self.index_name,
            query={"term": {"knowledge_key": knowledge_key}},
        )
        return int(response["count"])

    async def delete_source(self, source_id: str) -> int:
        response = await self.client.delete_by_query(
            index=self.index_name,
            query={"term": {"source_id": source_id}},
            refresh=True,
            conflicts="proceed",
        )
        return int(response.get("deleted", 0))

    # 检查 Elasticsearch 服务是否可以访问。
    async def ping(self) -> bool:
        return bool(await self.client.ping())

    # 使用多字段 BM25 和权限元数据过滤召回关键词候选。
    async def bm25_search(
        self,
        query: str,
        knowledge_keys: list[str],
        top_k: int,
        tenant_id: str,
        visibility: str,
        device_category: str | None,
        device_model: str | None,
    ) -> list[RetrievalCandidate]:
        response = await self.client.search(
            index=self.index_name,
            size=top_k,
            query={
                "bool": {
                    "must": [
                        {
                            "multi_match": {
                                "query": query,
                                "fields": ["title^3", "section_path^2", "content"],
                                "type": "best_fields",
                            }
                        }
                    ],
                    "filter": self._filters(
                        knowledge_keys,
                        tenant_id,
                        visibility,
                        device_category,
                        device_model,
                    ),
                }
            },
            source_excludes=["embedding"],
        )
        return [
            self._candidate(hit, rank, "bm25")
            for rank, hit in enumerate(response["hits"]["hits"], start=1)
        ]

    # 使用带前置过滤的 kNN 查询召回语义相似候选。
    async def vector_search(
        self,
        vector: list[float],
        knowledge_keys: list[str],
        top_k: int,
        tenant_id: str,
        visibility: str,
        device_category: str | None,
        device_model: str | None,
    ) -> list[RetrievalCandidate]:
        filters = self._filters(
            knowledge_keys,
            tenant_id,
            visibility,
            device_category,
            device_model,
        )
        response = await self.client.search(
            index=self.index_name,
            size=top_k,
            knn={
                "field": "embedding",
                "query_vector": vector,
                "k": top_k,
                "num_candidates": max(50, top_k * 5),
                "filter": {"bool": {"filter": filters}},
            },
            source_excludes=["embedding"],
        )
        return [
            self._candidate(hit, rank, "dense")
            for rank, hit in enumerate(response["hits"]["hits"], start=1)
        ]

    # 根据知识版本、租户可见性和设备条件构建统一过滤器。
    @staticmethod
    def _filters(
        knowledge_keys: list[str],
        tenant_id: str,
        visibility: str,
        device_category: str | None,
        device_model: str | None,
    ) -> list[dict[str, Any]]:
        filters: list[dict[str, Any]] = [{"terms": {"knowledge_key": knowledge_keys}}]
        if visibility == "tenant":
            filters.append(
                {
                    "bool": {
                        "should": [
                            {"term": {"visibility": "public"}},
                            {
                                "bool": {
                                    "filter": [
                                        {"term": {"visibility": "tenant"}},
                                        {"term": {"tenant_id": tenant_id}},
                                    ]
                                }
                            },
                        ],
                        "minimum_should_match": 1,
                    }
                }
            )
        else:
            filters.append({"term": {"visibility": "public"}})
        if device_category:
            filters.append({"term": {"device_category": device_category}})
        if device_model:
            filters.append({"term": {"device_model": device_model}})
        return filters

    # 将 Elasticsearch 原始命中转换为内部检索候选模型。
    @staticmethod
    def _candidate(
        hit: dict[str, Any], rank: int, origin: str
    ) -> RetrievalCandidate:
        source = hit["_source"]
        raw_score = float(hit.get("_score") or 0.0)
        return RetrievalCandidate(
            chunk_id=source["chunk_id"],
            source_id=source["source_id"],
            source_type=SourceType(source["source_type"]),
            source_version=source["source_version"],
            title=source["title"],
            section_path=source.get("section_path", ""),
            content=source["content"],
            rank=rank,
            score=raw_score,
            retrieval_sources=[origin],
            bm25_score=raw_score if origin == "bm25" else None,
            vector_score=raw_score if origin == "dense" else None,
        )
