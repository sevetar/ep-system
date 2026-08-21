from __future__ import annotations

import pymysql

from flowfix_agent.dispatch.domain.models import DispatchDecision
from flowfix_agent.memory.mysql import (
    MySQLStoreConfig,
    ensure_database,
    mysql_session,
)


# 基于 MySQL 的幂等派单决策仓库：与 SQLite 版本保持相同的幂等语义。
class MySQLDispatchDecisionRepository:
    # 连接配置建库建表：以事件标识为主键保证幂等。
    def __init__(self, config: MySQLStoreConfig) -> None:
        self.config = config
        ensure_database(config)
        self._initialize()

    # 创建 dispatch_decisions 表，payload 使用 JSON 列。
    def _initialize(self) -> None:
        with mysql_session(self.config) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """CREATE TABLE IF NOT EXISTS dispatch_decisions (
                    event_id VARCHAR(128) NOT NULL, payload JSON NOT NULL,
                    PRIMARY KEY (event_id))
                    CHARACTER SET utf8mb4"""
                )

    # 按事件标识读取决策，返回隔离的深拷贝。
    async def get_by_event(self, event_id: str) -> DispatchDecision | None:
        with mysql_session(self.config) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT payload FROM dispatch_decisions WHERE event_id=%s",
                    (event_id,),
                )
                row = cursor.fetchone()
        if not row:
            return None
        return DispatchDecision.model_validate_json(row[0])

    # 仅在事件尚无决策时保存，以保证跨重启的幂等写入。
    async def save_if_absent(self, decision: DispatchDecision) -> DispatchDecision:
        with mysql_session(self.config) as connection:
            with connection.cursor() as cursor:
                try:
                    cursor.execute(
                        "INSERT INTO dispatch_decisions VALUES (%s, %s)",
                        (decision.event_id, decision.model_dump_json()),
                    )
                    return decision.model_copy(deep=True)
                except pymysql.err.IntegrityError:
                    cursor.execute(
                        "SELECT payload FROM dispatch_decisions WHERE event_id=%s",
                        (decision.event_id,),
                    )
                    row = cursor.fetchone()
                    return DispatchDecision.model_validate_json(row[0])
