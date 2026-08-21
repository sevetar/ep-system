from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

# 仅用于类型标注，避免 ports <-> 实现模块的运行时循环导入。
if TYPE_CHECKING:
    from flowfix_agent.memory.conversation import (
        ConversationNamespace,
        ConversationState,
    )
    from flowfix_agent.memory.task_artifact import TaskArtifactRecord


# 会话存储端口：按命名空间读取、以乐观锁写入会话状态。
class ConversationStorePort(Protocol):
    def load(
        self, namespace: ConversationNamespace
    ) -> ConversationState | None: ...

    def save(
        self, state: ConversationState, *, expected_version: int
    ) -> ConversationState: ...


# Task/Artifact 存储端口：版本化读写与计划内历史读取。
class TaskArtifactStorePort(Protocol):
    def get(
        self, tenant_id: str, thread_id: str, plan_id: str, entity_id: str, kind: str
    ) -> TaskArtifactRecord | None: ...

    def put(
        self, record: TaskArtifactRecord, *, expected_version: int
    ) -> TaskArtifactRecord: ...

    def list_plan(
        self, tenant_id: str, thread_id: str, plan_id: str
    ) -> list[TaskArtifactRecord]: ...
