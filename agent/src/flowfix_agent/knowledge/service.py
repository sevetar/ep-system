from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any

from flowfix_agent.knowledge.markdown import MarkdownKnowledgeLoader
from flowfix_agent.knowledge.models import (
    CatalogRecord,
    IngestionReport,
    SourceIngestionResult,
    SourceSnapshot,
    SourceType,
)
from flowfix_agent.knowledge.ports import (
    EmbeddingPort,
    KnowledgeCatalogPort,
    KnowledgeIndexPort,
    TracePort,
)


# 编排知识发现、快照、切分、向量化、索引和版本激活流程。
class KnowledgeIngestionService:
    # 注入摄取流程所需的加载器、模型、索引、目录和追踪端口。
    def __init__(
        self,
        loader: MarkdownKnowledgeLoader,
        embedding: EmbeddingPort,
        index: KnowledgeIndexPort,
        catalog: KnowledgeCatalogPort,
        trace: TracePort,
        embedding_batch_size: int,
    ) -> None:
        self.loader = loader
        self.embedding = embedding
        self.index = index
        self.catalog = catalog
        self.trace = trace
        self.embedding_batch_size = embedding_batch_size

    # 批量摄取指定路径下的知识源并汇总执行报告。
    async def ingest(
        self,
        requested_paths: list[str],
        source_type: SourceType = SourceType.PLATFORM_DOC,
        recreate_index: bool = False,
    ) -> IngestionReport:
        # 生成追踪 ID 并记录本次摄取的起始时间，用于后续 Trace 耗时统计。
        trace_id = uuid.uuid4().hex
        started = time.perf_counter()
        # 确保索引存在（可按需重建），避免后续写入时索引缺失。
        await self.index.ensure_index(recreate=recreate_index)
        # 根据请求路径发现实际待摄取的知识文件。
        paths = self.loader.discover(requested_paths)
        results: list[SourceIngestionResult] = []

        # 逐个文件执行摄取，收集每个来源的摄取结果。
        for path in paths:
            result = await self._ingest_one(path, source_type, trace_id)
            results.append(result)

        report = IngestionReport(
            trace_id=trace_id,
            index=self.index.index_name,
            indexed_chunks=sum(item.chunks for item in results if item.status == "indexed"),
            skipped_sources=sum(item.status == "skipped" for item in results),
            failed_sources=sum(item.status == "failed" for item in results),
            sources=results,
        )
        # 上报本次摄取的汇总结果（含耗时），便于离线排查与审计。
        await self.trace.emit(
            "ingestion.completed",
            trace_id,
            {
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                **report.model_dump(mode="json"),
            },
        )
        return report

    # 摄取单个知识文件，并对未变化内容跳过重复索引。
    async def _ingest_one(
        self, path: Path, source_type: SourceType, trace_id: str
    ) -> SourceIngestionResult:
        snapshot = self.loader.snapshot(path, source_type=source_type)
        return await self._ingest_snapshot(snapshot, trace_id=trace_id)

    async def ingest_snapshot(
        self,
        snapshot: SourceSnapshot,
        *,
        metadata: dict[str, Any] | None = None,
        trace_id: str | None = None,
    ) -> SourceIngestionResult:
        """摄取运行时生成的可信快照，供工单案例等非文件知识源复用。"""
        await self.index.ensure_index()
        return await self._ingest_snapshot(
            snapshot,
            trace_id=trace_id or uuid.uuid4().hex,
            metadata=metadata,
        )

    async def _ingest_snapshot(
        self,
        snapshot: SourceSnapshot,
        *,
        trace_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> SourceIngestionResult:
        current = await self.catalog.get(snapshot.source_id)
        # 内容哈希未变化且索引块数与目录一致时，跳过重复索引。
        if current and current.content_hash == snapshot.content_hash:
            projected_chunks = await self.index.count_knowledge_key(
                current.knowledge_key
            )
            if projected_chunks == current.indexed_chunks:
                return SourceIngestionResult(
                    source_id=snapshot.source_id,
                    version=snapshot.version,
                    status="skipped",
                    chunks=current.indexed_chunks,
                )
        try:
            # 切分快照并分批向量化，校验批量大小与向量维度。
            chunks = self.loader.chunk(snapshot)
            if metadata:
                for chunk in chunks:
                    chunk.metadata.update(metadata)
            for start in range(0, len(chunks), self.embedding_batch_size):
                batch = chunks[start : start + self.embedding_batch_size]
                vectors = await self.embedding.embed_documents([chunk.content for chunk in batch])
                if len(vectors) != len(batch):
                    raise ValueError("Embedding provider returned a different batch size")
                for chunk, vector in zip(batch, vectors, strict=True):
                    if len(vector) != self.embedding.dimensions:
                        raise ValueError(
                            f"Embedding dimension mismatch for {chunk.chunk_id}: {len(vector)}"
                        )
                    chunk.embedding = vector
            # 写入索引并回查校验，块数不一致则视为失败。
            indexed = await self.index.index_chunks(chunks)
            verified = await self.index.count_knowledge_key(snapshot.knowledge_key)
            if indexed != len(chunks) or verified != len(chunks):
                raise ValueError(
                    f"Index validation failed: expected={len(chunks)}, "
                    f"indexed={indexed}, found={verified}"
                )
            # 索引校验通过后，激活该来源的新版本到目录。
            await self.catalog.activate(
                CatalogRecord(
                    source_id=snapshot.source_id,
                    source_type=snapshot.source_type,
                    active_version=snapshot.version,
                    knowledge_key=snapshot.knowledge_key,
                    content_hash=snapshot.content_hash,
                    indexed_chunks=len(chunks),
                    tenant_id=snapshot.tenant_id,
                    visibility=snapshot.visibility,
                )
            )
            await self.trace.emit(
                "ingestion.source_indexed",
                trace_id,
                {
                    "source_id": snapshot.source_id,
                    "version": snapshot.version,
                    "chunks": len(chunks),
                },
            )
            return SourceIngestionResult(
                source_id=snapshot.source_id,
                version=snapshot.version,
                status="indexed",
                chunks=len(chunks),
            )
        except Exception as exc:
            # 任一环节异常均记录失败原因并返回失败结果，不影响其余来源。
            await self.trace.emit(
                "ingestion.source_failed",
                trace_id,
                {
                    "source_id": snapshot.source_id,
                    "version": snapshot.version,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
            )
            return SourceIngestionResult(
                source_id=snapshot.source_id,
                version=snapshot.version,
                status="failed",
                error=f"{type(exc).__name__}: {exc}",
            )
