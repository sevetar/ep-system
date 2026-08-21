from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path

from flowfix_agent.knowledge.models import CatalogRecord


# 使用本地 JSON 文件持久化知识源的激活版本目录。
class FileKnowledgeCatalog:
    # 初始化目录文件路径和进程内异步锁。
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = asyncio.Lock()

    # 按知识源标识读取当前激活的目录记录。
    async def get(self, source_id: str) -> CatalogRecord | None:
        records = await self._read()
        payload = records.get(source_id)
        return CatalogRecord.model_validate(payload) if payload else None

    # 返回目录中全部处于激活状态的知识源记录。
    async def list_active(self) -> list[CatalogRecord]:
        records = await self._read()
        return [CatalogRecord.model_validate(value) for value in records.values()]

    # 原子写入并激活指定知识源的最新版本记录。
    async def activate(self, record: CatalogRecord) -> None:
        async with self._lock:
            records = await asyncio.to_thread(self._read_sync)
            records[record.source_id] = record.model_dump(mode="json")
            await asyncio.to_thread(self._write_sync, records)

    async def deactivate(self, source_id: str) -> CatalogRecord | None:
        async with self._lock:
            records = await asyncio.to_thread(self._read_sync)
            payload = records.pop(source_id, None)
            if payload is None:
                return None
            await asyncio.to_thread(self._write_sync, records)
            return CatalogRecord.model_validate(payload)

    # 在异步锁保护下把同步文件读取调度到工作线程。
    async def _read(self) -> dict[str, dict]:
        async with self._lock:
            return await asyncio.to_thread(self._read_sync)

    # 从磁盘同步读取并解析目录文件。
    def _read_sync(self) -> dict[str, dict]:
        if not self.path.exists():
            return {}
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        return dict(payload.get("sources", {}))

    # 通过临时文件替换方式同步落盘，避免写出半成品目录。
    def _write_sync(self, records: dict[str, dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        file_descriptor, temporary_name = tempfile.mkstemp(
            dir=self.path.parent,
            prefix=f".{self.path.name}.",
            suffix=".tmp",
            text=True,
        )
        try:
            with os.fdopen(file_descriptor, "w", encoding="utf-8") as handle:
                json.dump({"sources": records}, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, self.path)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)
