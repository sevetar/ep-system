from __future__ import annotations

import asyncio
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from flowfix_agent.knowledge.models import (
    WorkOrderKnowledgeRecord,
    WorkOrderKnowledgeStatus,
)


class FileWorkOrderKnowledgeLedger:
    """本地持久化工单知识处理台账，支撑状态查询和事件级幂等。"""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = asyncio.Lock()

    async def get(self, event_id: str) -> WorkOrderKnowledgeRecord | None:
        async with self._lock:
            records = await asyncio.to_thread(self._read_sync)
        payload = records.get(event_id)
        return WorkOrderKnowledgeRecord.model_validate(payload) if payload else None

    async def save(self, record: WorkOrderKnowledgeRecord) -> None:
        async with self._lock:
            records = await asyncio.to_thread(self._read_sync)
            records[record.event_id] = record.model_dump(mode="json")
            await asyncio.to_thread(self._write_sync, records)

    async def revoke_source(
        self, source_id: str, reason: str
    ) -> list[WorkOrderKnowledgeRecord]:
        now = datetime.now(UTC)
        changed: list[WorkOrderKnowledgeRecord] = []
        async with self._lock:
            records = await asyncio.to_thread(self._read_sync)
            for event_id, payload in records.items():
                record = WorkOrderKnowledgeRecord.model_validate(payload)
                if record.source_id != source_id:
                    continue
                record.status = WorkOrderKnowledgeStatus.REVOKED
                record.revoke_reason = reason
                record.revoked_at = now
                record.updated_at = now
                records[event_id] = record.model_dump(mode="json")
                changed.append(record)
            if changed:
                await asyncio.to_thread(self._write_sync, records)
        return changed

    def _read_sync(self) -> dict[str, dict]:
        if not self.path.exists():
            return {}
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        return dict(payload.get("events", {}))

    def _write_sync(self, records: dict[str, dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            dir=self.path.parent,
            prefix=f".{self.path.name}.",
            suffix=".tmp",
            text=True,
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump({"events": records}, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, self.path)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)
