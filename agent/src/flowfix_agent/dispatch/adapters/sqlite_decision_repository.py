from __future__ import annotations

import sqlite3
from pathlib import Path

from flowfix_agent.dispatch.domain.models import DispatchDecision


# 基于 SQLite 的幂等派单决策仓库：重启后仍保留事件级决策，保证重放不重复派单。
class SQLiteDispatchDecisionRepository:
    # 初始化数据库路径并建表。
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    # 建立 sqlite3 连接并启用 Row 工厂。
    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    # 创建 dispatch_decisions 表，以事件标识为主键保证幂等。
    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS dispatch_decisions (
                event_id TEXT PRIMARY KEY, payload TEXT NOT NULL)"""
            )

    # 按事件标识读取决策，返回隔离的深拷贝。
    async def get_by_event(self, event_id: str) -> DispatchDecision | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM dispatch_decisions WHERE event_id=?",
                (event_id,),
            ).fetchone()
        if not row:
            return None
        return DispatchDecision.model_validate_json(row["payload"])

    # 仅在事件尚无决策时保存，以保证跨重启的幂等写入。
    async def save_if_absent(self, decision: DispatchDecision) -> DispatchDecision:
        with self._connect() as connection:
            try:
                connection.execute(
                    "INSERT INTO dispatch_decisions VALUES (?, ?)",
                    (decision.event_id, decision.model_dump_json()),
                )
                return decision.model_copy(deep=True)
            except sqlite3.IntegrityError:
                row = connection.execute(
                    "SELECT payload FROM dispatch_decisions WHERE event_id=?",
                    (decision.event_id,),
                ).fetchone()
                return DispatchDecision.model_validate_json(row["payload"])
