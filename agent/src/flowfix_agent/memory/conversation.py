from __future__ import annotations

import re
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pymysql
from pydantic import BaseModel, Field

from flowfix_agent.memory.errors import MemoryConflictError
from flowfix_agent.memory.mysql import (
    TS_FORMAT,
    MySQLStoreConfig,
    ensure_database,
    mysql_session,
)
from flowfix_agent.memory.ports import ConversationStorePort


# 会话命名空间：tenant + user + thread，隔离不同租户/用户/会话。
class ConversationNamespace(BaseModel):
    tenant_id: str
    user_id: str
    thread_id: str


# 一条会话消息：角色、内容与创建时间。
class ConversationMessage(BaseModel):
    role: str
    content: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


# 会话结束时的结构化总结：目标、已确认事实、已解决/未解决项、引用与后续动作。
class ConversationSummary(BaseModel):
    goal: str | None = None
    confirmed_facts: list[str] = Field(default_factory=list)
    resolved_items: list[str] = Field(default_factory=list)
    unresolved_items: list[str] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)


# 保存业务 Graph 启动前尚待用户补槽的原始请求，支持同一会话继续执行。
class PendingTurn(BaseModel):
    original_message: str
    missing_fields: list[str] = Field(default_factory=list)
    trace_id: str
    # 业务链已确定时保存其 route；仅意图模糊时为 None，补充后才重新分类。
    route_type: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


# 会话状态：近期消息、滚动摘要、实体槽、当前主题、过期时间与版本。
class ConversationState(BaseModel):
    namespace: ConversationNamespace
    recent_messages: list[ConversationMessage] = Field(default_factory=list)
    rolling_summary: str = ""
    entity_slots: dict[str, str] = Field(default_factory=dict)
    current_topic: str | None = None
    final_summary: ConversationSummary | None = None
    pending_turn: PendingTurn | None = None
    last_active_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime
    version: int = 0


# 一轮问答的准备结果：原问题、改写后问题与当前会话状态。
class PreparedConversation(BaseModel):
    original_query: str
    rewritten_query: str
    state: ConversationState


# 基于 SQLite 的会话存储，支持按命名空间读取、写入与版本冲突检测。
class SQLiteConversationStore:
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

    # 创建 conversations 表，主键为 tenant+user+thread。
    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS conversations (
                tenant_id TEXT NOT NULL, user_id TEXT NOT NULL, thread_id TEXT NOT NULL,
                version INTEGER NOT NULL, expires_at TEXT NOT NULL, payload TEXT NOT NULL,
                PRIMARY KEY (tenant_id, user_id, thread_id))"""
            )

    # 读取会话状态，过期时删除并返回 None。
    def load(self, namespace: ConversationNamespace) -> ConversationState | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM conversations WHERE tenant_id=? AND user_id=? AND thread_id=?",
                (namespace.tenant_id, namespace.user_id, namespace.thread_id),
            ).fetchone()
        if not row:
            return None
        state = ConversationState.model_validate_json(row["payload"])
        if state.expires_at <= datetime.now(UTC):
            with self._connect() as connection:
                connection.execute(
                    "DELETE FROM conversations WHERE tenant_id=? AND user_id=? AND thread_id=?",
                    (namespace.tenant_id, namespace.user_id, namespace.thread_id),
                )
            return None
        return state

    # 以乐观锁写入会话：expected_version 不匹配时抛出版本冲突。
    def save(self, state: ConversationState, *, expected_version: int) -> ConversationState:
        next_state = state.model_copy(
            update={"version": expected_version + 1, "last_active_at": datetime.now(UTC)}
        )
        payload = next_state.model_dump_json()
        ns = state.namespace
        with self._connect() as connection:
            if expected_version == 0:
                try:
                    connection.execute(
                        "INSERT INTO conversations VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            ns.tenant_id,
                            ns.user_id,
                            ns.thread_id,
                            next_state.version,
                            next_state.expires_at.isoformat(),
                            payload,
                        ),
                    )
                    return next_state
                except sqlite3.IntegrityError as exc:
                    raise MemoryConflictError("conversation already exists") from exc
            cursor = connection.execute(
                """UPDATE conversations SET version=?, expires_at=?, payload=?
                WHERE tenant_id=? AND user_id=? AND thread_id=? AND version=?""",
                (
                    next_state.version,
                    next_state.expires_at.isoformat(),
                    payload,
                    ns.tenant_id,
                    ns.user_id,
                    ns.thread_id,
                    expected_version,
                ),
            )
            if cursor.rowcount != 1:
                raise MemoryConflictError("conversation version conflict")
        return next_state


# 基于 MySQL 的会话存储，与 SQLite 版本保持相同的命名空间与乐观锁语义。
class MySQLConversationStore:
    # 连接配置建库建表：主键为 tenant+user+thread。
    def __init__(self, config: MySQLStoreConfig) -> None:
        self.config = config
        ensure_database(config)
        self._initialize()

    # 创建 conversations 表，payload 使用 JSON 列。
    def _initialize(self) -> None:
        with mysql_session(self.config) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """CREATE TABLE IF NOT EXISTS conversations (
                    tenant_id VARCHAR(128) NOT NULL, user_id VARCHAR(128) NOT NULL,
                    thread_id VARCHAR(128) NOT NULL, version INT NOT NULL,
                    expires_at DATETIME NOT NULL, payload JSON NOT NULL,
                    PRIMARY KEY (tenant_id, user_id, thread_id))
                    CHARACTER SET utf8mb4"""
                )

    # 读取会话状态，过期时删除并返回 None。
    def load(self, namespace: ConversationNamespace) -> ConversationState | None:
        where = "tenant_id=%s AND user_id=%s AND thread_id=%s"
        with mysql_session(self.config) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT payload FROM conversations WHERE {where}",
                    (namespace.tenant_id, namespace.user_id, namespace.thread_id),
                )
                row = cursor.fetchone()
        if not row:
            return None
        state = ConversationState.model_validate_json(row[0])
        if state.expires_at <= datetime.now(UTC):
            with mysql_session(self.config) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"DELETE FROM conversations WHERE {where}",
                        (namespace.tenant_id, namespace.user_id, namespace.thread_id),
                    )
            return None
        return state

    # 以乐观锁写入会话：expected_version 不匹配时抛出版本冲突。
    def save(self, state: ConversationState, *, expected_version: int) -> ConversationState:
        next_state = state.model_copy(
            update={"version": expected_version + 1, "last_active_at": datetime.now(UTC)}
        )
        payload = next_state.model_dump_json()
        ns = state.namespace
        with mysql_session(self.config) as connection:
            with connection.cursor() as cursor:
                if expected_version == 0:
                    try:
                        cursor.execute(
                            "INSERT INTO conversations VALUES (%s, %s, %s, %s, %s, %s)",
                            (
                                ns.tenant_id,
                                ns.user_id,
                                ns.thread_id,
                                next_state.version,
                                next_state.expires_at.strftime(TS_FORMAT),
                                payload,
                            ),
                        )
                        return next_state
                    except pymysql.err.IntegrityError as exc:
                        raise MemoryConflictError("conversation already exists") from exc
                cursor.execute(
                    """UPDATE conversations SET version=%s, expires_at=%s, payload=%s
                    WHERE tenant_id=%s AND user_id=%s AND thread_id=%s AND version=%s""",
                    (
                        next_state.version,
                        next_state.expires_at.strftime(TS_FORMAT),
                        payload,
                        ns.tenant_id,
                        ns.user_id,
                        ns.thread_id,
                        expected_version,
                    ),
                )
                if cursor.rowcount != 1:
                    raise MemoryConflictError("conversation version conflict")
        return next_state


# 会话服务：改写、记录对话轮次、窗口压缩与结束总结。
class ConversationService:
    # 配置存储、TTL、近期窗口与摘要长度上限。
    def __init__(
        self,
        store: ConversationStorePort,
        *,
        ttl_hours: int = 24,
        recent_limit: int = 8,
        summary_char_limit: int = 1200,
    ) -> None:
        self.store = store
        self.ttl = timedelta(hours=ttl_hours)
        self.recent_limit = recent_limit
        self.summary_char_limit = summary_char_limit

    # 加载会话并做确定性 Query Rewrite，返回准备结果。
    def prepare(self, namespace: ConversationNamespace, query: str) -> PreparedConversation:
        state = self.store.load(namespace) or ConversationState(
            namespace=namespace, expires_at=datetime.now(UTC) + self.ttl
        )
        rewritten = self._rewrite(query, state)
        return PreparedConversation(
            original_query=query, rewritten_query=rewritten, state=state
        )

    # 读取当前未完成请求，供统一入口把用户补充与原始意图合并。
    def load_pending(self, namespace: ConversationNamespace) -> PendingTurn | None:
        state = self.store.load(namespace)
        return state.pending_turn if state else None

    # 以乐观锁保存待补槽请求；同一线程的新请求会更新现有 pending turn。
    def save_pending(self, namespace: ConversationNamespace, pending: PendingTurn) -> None:
        state = self.store.load(namespace) or ConversationState(
            namespace=namespace, expires_at=datetime.now(UTC) + self.ttl
        )
        state.pending_turn = pending
        state.expires_at = datetime.now(UTC) + self.ttl
        self.store.save(state, expected_version=state.version)

    # 成功续接后清除 pending turn，防止后续无关消息被重复拼接。
    def clear_pending(self, namespace: ConversationNamespace) -> None:
        state = self.store.load(namespace)
        if state is None or state.pending_turn is None:
            return
        state.pending_turn = None
        self.store.save(state, expected_version=state.version)

    # 记录一轮问答：追加消息、更新主题与实体，超窗口时压缩，可选结束总结。
    def record_turn(
        self,
        prepared: PreparedConversation,
        answer: str,
        *,
        citations: list[str] | None = None,
        end_conversation: bool = False,
    ) -> ConversationState:
        # 深拷贝准备阶段的状态，避免改动调用方持有的原始对象。
        state = prepared.state.model_copy(deep=True)
        # 把本轮用户原问题与助手答案追加进近期消息窗口。
        state.recent_messages.extend(
            [
                ConversationMessage(role="user", content=prepared.original_query),
                ConversationMessage(role="assistant", content=answer),
            ]
        )
        # 用原问题更新主题（无新主题时保留旧主题）并增量合并提取的实体槽位。
        state.current_topic = self._topic(prepared.original_query) or state.current_topic
        state.entity_slots.update(self._entities(prepared.original_query))
        # 超过近期窗口上限时，把最旧的多余消息并入滚动摘要并截断，
        # 保证短问句改写始终有上下文，同时控制单条会话的存储体积。
        if len(state.recent_messages) > self.recent_limit:
            # 取出超窗的最旧消息：保留窗口尾部 recent_limit 条，前面的全部视为溢出。
            overflow = state.recent_messages[: -self.recent_limit]
            # 把溢出的多条消息按顺序拼接成一条紧凑要点，方便整体并入摘要。
            compact = " | ".join(message.content for message in overflow)
            # 新摘要 = 旧摘要 + 溢出要点；strip 去掉拼接产生的首尾分隔符。
            combined = (state.rolling_summary + " | " + compact).strip(" |")
            # 摘要整体截断到字符上限，只保留最近部分，控制单条会话的存储体积。
            state.rolling_summary = combined[-self.summary_char_limit :]
            # 近期窗口收缩为尾部 recent_limit 条，溢出消息已被摘要承接。
            state.recent_messages = state.recent_messages[-self.recent_limit :]
        # 每次交互后顺延过期时间，保持滑动 TTL。
        state.expires_at = datetime.now(UTC) + self.ttl
        # 结束会话时固化最终总结：主题作为目标，实体槽值作为已确认事实。
        if end_conversation:
            state.final_summary = ConversationSummary(
                goal=state.current_topic,
                confirmed_facts=list(dict.fromkeys(state.entity_slots.values())),
                resolved_items=[prepared.original_query],
                citations=citations or [],
            )
        # 以 prepare 阶段读取到的版本作乐观锁写入，版本被并发修改时抛冲突。
        return self.store.save(state, expected_version=prepared.state.version)

    # 引用式短问句补全上下文，返回改写后的问题。
    @staticmethod
    def _rewrite(query: str, state: ConversationState) -> str:
        refers_back = len(query) < 24 or any(word in query for word in ("它", "这个", "上述", "那"))
        if not refers_back:
            return query
        context = state.current_topic or state.rolling_summary
        if not context and state.recent_messages:
            context = state.recent_messages[-1].content
        return f"上下文：{context}；当前问题：{query}" if context else query

    # 取问题前 120 字符作为当前主题。
    @staticmethod
    def _topic(query: str) -> str:
        return query.strip()[:120]

    # 用正则提取问题中的设备号与工单号实体。
    @staticmethod
    def _entities(query: str) -> dict[str, str]:
        entities: dict[str, str] = {}
        for label, pattern in {
            "device_id": r"(?:设备|device)[：:#\s-]*([A-Za-z0-9_-]+)",
            "work_order_id": r"(?:工单|work\s*order)[：:#\s-]*([A-Za-z0-9_-]+)",
        }.items():
            match = re.search(pattern, query, re.I)
            if match:
                entities[label] = match.group(1)
        return entities
