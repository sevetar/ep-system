from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


# 将结构化链路事件按 JSONL 格式追加到本地文件。
class JsonlTraceSink:
    # 初始化追踪文件路径和进程内异步写锁。
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = asyncio.Lock()

    # 构造带时间戳的事件并在线程中安全追加到文件。
    async def emit(self, event_type: str, trace_id: str, payload: dict[str, Any]) -> None:
        event = {
            "timestamp": datetime.now(UTC).isoformat(),
            "event_type": event_type,
            "trace_id": trace_id,
            "payload": payload,
        }
        encoded = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
        async with self._lock:
            await asyncio.to_thread(self._append, encoded)

    # 同步创建目录并向追踪文件追加一行编码后的 JSON。
    def _append(self, encoded: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(encoded)
            handle.write("\n")
