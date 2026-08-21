from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import pymysql
from pydantic import BaseModel, Field

from flowfix_agent.memory.errors import MemoryConflictError
from flowfix_agent.memory.mysql import (
    MySQLStoreConfig,
    ensure_database,
    mysql_session,
)


# Task/Artifact 持久化记录：租户、计划、实体、类型、负载与版本。
class TaskArtifactRecord(BaseModel):
    tenant_id: str
    thread_id: str
    plan_id: str
    entity_id: str
    kind: Literal["plan", "task", "artifact", "patch"]
    payload: dict[str, Any]
    source: str
    trace_id: str
    schema_version: str = "1"
    version: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC) + timedelta(days=30)
    )


# 基于 SQLite 的 Task/Artifact 存储，支持版本化写入与计划内历史读取。
class SQLiteTaskArtifactStore:
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

    # 创建 task_artifacts 表，主键含租户/计划/实体/类型。
    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS task_artifacts (
                tenant_id TEXT NOT NULL, thread_id TEXT NOT NULL, plan_id TEXT NOT NULL,
                entity_id TEXT NOT NULL, kind TEXT NOT NULL, version INTEGER NOT NULL,
                payload TEXT NOT NULL,
                PRIMARY KEY (tenant_id, thread_id, plan_id, entity_id, kind))"""
            )

    # 读取单条记录，过期时返回 None。
    def get(
        self, tenant_id: str, thread_id: str, plan_id: str, entity_id: str, kind: str
    ) -> TaskArtifactRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                """SELECT payload FROM task_artifacts WHERE tenant_id=? AND thread_id=?
                AND plan_id=? AND entity_id=? AND kind=?""",
                (tenant_id, thread_id, plan_id, entity_id, kind),
            ).fetchone()
        if not row:
            return None
        record = TaskArtifactRecord.model_validate_json(row["payload"])
        return None if record.expires_at <= datetime.now(UTC) else record

    # 以乐观锁写入记录，expected_version 不匹配时抛出版本冲突。
    def put(
        self, record: TaskArtifactRecord, *, expected_version: int
    ) -> TaskArtifactRecord:
        now = datetime.now(UTC)
        saved = record.model_copy(
            update={"version": expected_version + 1, "updated_at": now}
        )
        values = (
            saved.tenant_id,
            saved.thread_id,
            saved.plan_id,
            saved.entity_id,
            saved.kind,
        )
        with self._connect() as connection:
            if expected_version == 0:
                try:
                    connection.execute(
                        "INSERT INTO task_artifacts VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (*values, saved.version, saved.model_dump_json()),
                    )
                    return saved
                except sqlite3.IntegrityError as exc:
                    raise MemoryConflictError("task/artifact already exists") from exc
            cursor = connection.execute(
                """UPDATE task_artifacts SET version=?, payload=? WHERE tenant_id=?
                AND thread_id=? AND plan_id=? AND entity_id=? AND kind=? AND version=?""",
                (saved.version, saved.model_dump_json(), *values, expected_version),
            )
            if cursor.rowcount != 1:
                raise MemoryConflictError("task/artifact version conflict")
        return saved

    # 列出指定计划下的全部记录，按类型与实体排序。
    def list_plan(self, tenant_id: str, thread_id: str, plan_id: str) -> list[TaskArtifactRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT payload FROM task_artifacts WHERE tenant_id=? AND thread_id=?
                AND plan_id=? ORDER BY kind, entity_id""",
                (tenant_id, thread_id, plan_id),
            ).fetchall()
        return [TaskArtifactRecord.model_validate_json(row["payload"]) for row in rows]


# 基于 MySQL 的 Task/Artifact 存储，与 SQLite 版本保持相同的乐观锁语义。
class MySQLTaskArtifactStore:
    # 连接配置建库建表：主键含租户/计划/实体/类型。
    def __init__(self, config: MySQLStoreConfig) -> None:
        self.config = config
        ensure_database(config)
        self._initialize()

    # 创建 task_artifacts 表，payload 使用 JSON 列。
    def _initialize(self) -> None:
        with mysql_session(self.config) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """CREATE TABLE IF NOT EXISTS task_artifacts (
                    tenant_id VARCHAR(128) NOT NULL, thread_id VARCHAR(128) NOT NULL,
                    plan_id VARCHAR(128) NOT NULL, entity_id VARCHAR(128) NOT NULL,
                    kind VARCHAR(32) NOT NULL, version INT NOT NULL,
                    payload JSON NOT NULL,
                    PRIMARY KEY (tenant_id, thread_id, plan_id, entity_id, kind))
                    CHARACTER SET utf8mb4"""
                )

    # 读取单条记录，过期时返回 None。
    def get(
        self, tenant_id: str, thread_id: str, plan_id: str, entity_id: str, kind: str
    ) -> TaskArtifactRecord | None:
        with mysql_session(self.config) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """SELECT payload FROM task_artifacts WHERE tenant_id=%s AND thread_id=%s
                    AND plan_id=%s AND entity_id=%s AND kind=%s""",
                    (tenant_id, thread_id, plan_id, entity_id, kind),
                )
                row = cursor.fetchone()
        if not row:
            return None
        record = TaskArtifactRecord.model_validate_json(row[0])
        return None if record.expires_at <= datetime.now(UTC) else record

    # 以乐观锁写入记录，expected_version 不匹配时抛出版本冲突。
    def put(
        self, record: TaskArtifactRecord, *, expected_version: int
    ) -> TaskArtifactRecord:
        now = datetime.now(UTC)
        saved = record.model_copy(
            update={"version": expected_version + 1, "updated_at": now}
        )
        values = (
            saved.tenant_id,
            saved.thread_id,
            saved.plan_id,
            saved.entity_id,
            saved.kind,
        )
        with mysql_session(self.config) as connection:
            with connection.cursor() as cursor:
                if expected_version == 0:
                    try:
                        cursor.execute(
                            "INSERT INTO task_artifacts VALUES (%s, %s, %s, %s, %s, %s, %s)",
                            (*values, saved.version, saved.model_dump_json()),
                        )
                        return saved
                    except pymysql.err.IntegrityError as exc:
                        raise MemoryConflictError("task/artifact already exists") from exc
                cursor.execute(
                    """UPDATE task_artifacts SET version=%s, payload=%s WHERE tenant_id=%s
                    AND thread_id=%s AND plan_id=%s AND entity_id=%s AND kind=%s AND version=%s""",
                    (saved.version, saved.model_dump_json(), *values, expected_version),
                )
                if cursor.rowcount != 1:
                    raise MemoryConflictError("task/artifact version conflict")
        return saved

    # 列出指定计划下的全部记录，按类型与实体排序。
    def list_plan(self, tenant_id: str, thread_id: str, plan_id: str) -> list[TaskArtifactRecord]:
        with mysql_session(self.config) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """SELECT payload FROM task_artifacts WHERE tenant_id=%s AND thread_id=%s
                    AND plan_id=%s ORDER BY kind, entity_id""",
                    (tenant_id, thread_id, plan_id),
                )
                rows = cursor.fetchall()
        return [TaskArtifactRecord.model_validate_json(row[0]) for row in rows]
