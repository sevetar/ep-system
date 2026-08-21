from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol

from flowfix_agent.knowledge.models import (
    CatalogRecord,
    KnowledgeChunk,
    WorkOrderKnowledgeRecord,
)


# 约束文档与查询向量生成器必须提供的能力。
class EmbeddingPort(Protocol):
    dimensions: int

    # 批量生成文档向量。
    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    # 生成单条查询向量。
    async def embed_query(self, text: str) -> list[float]: ...


# 约束知识检索投影必须提供的索引读写能力。
class KnowledgeIndexPort(Protocol):
    index_name: str

    # 确保目标索引可用，并支持显式重建。
    async def ensure_index(self, recreate: bool = False) -> None: ...

    # 批量写入知识分块并返回成功数量。
    async def index_chunks(self, chunks: Sequence[KnowledgeChunk]) -> int: ...

    # 统计指定知识版本键对应的分块数量。
    async def count_knowledge_key(self, knowledge_key: str) -> int: ...

    # 删除指定来源的全部历史检索投影，用于撤回错误案例。
    async def delete_source(self, source_id: str) -> int: ...

    # 检查索引服务是否可用。
    async def ping(self) -> bool: ...


# 约束知识目录的版本读取和激活写入能力。
class KnowledgeCatalogPort(Protocol):
    # 按知识源标识读取目录记录。
    async def get(self, source_id: str) -> CatalogRecord | None: ...

    # 列出全部激活的知识源记录。
    async def list_active(self) -> list[CatalogRecord]: ...

    # 激活指定知识源版本记录。
    async def activate(self, record: CatalogRecord) -> None: ...

    # 从在线目录移除知识源；先失活再清理投影可保证撤回立即生效。
    async def deactivate(self, source_id: str) -> CatalogRecord | None: ...


class WorkOrderKnowledgeLedgerPort(Protocol):
    async def get(self, event_id: str) -> WorkOrderKnowledgeRecord | None: ...

    async def save(self, record: WorkOrderKnowledgeRecord) -> None: ...

    async def revoke_source(
        self, source_id: str, reason: str
    ) -> list[WorkOrderKnowledgeRecord]: ...


# 约束链路追踪事件的统一输出能力。
class TracePort(Protocol):
    # 写出指定类型、链路标识和负载的追踪事件。
    async def emit(self, event_type: str, trace_id: str, payload: dict[str, Any]) -> None: ...
