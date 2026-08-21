from __future__ import annotations

from typing import Any, Protocol

from flowfix_agent.dispatch.domain.models import DispatchDecision
from flowfix_agent.dispatch.skills.manifest import DispatchSkill


# 定义调度策略注册、查询、激活和回滚能力。
class DispatchSkillRegistryPort(Protocol):
    # 注册一个不可变版本的调度策略。
    def register(self, skill: DispatchSkill) -> None: ...

    # 根据策略标识和版本读取策略。
    def get(self, skill_id: str, skill_version: str) -> DispatchSkill: ...

    # 读取当前生效的调度策略。
    def get_active(self) -> DispatchSkill: ...

    # 激活指定版本的调度策略。
    def activate(self, skill_id: str, skill_version: str) -> DispatchSkill: ...

    # 回滚到上一个生效的调度策略。
    def rollback(self) -> DispatchSkill: ...


# 定义按事件读取和幂等保存调度决策的能力。
class DispatchDecisionRepositoryPort(Protocol):
    # 按事件标识读取已有调度决策。
    async def get_by_event(self, event_id: str) -> DispatchDecision | None: ...

    # 当事件不存在决策时保存，并返回最终存储结果。
    async def save_if_absent(self, decision: DispatchDecision) -> DispatchDecision: ...


# 定义向外部观测系统发送调度追踪事件的能力。
class DispatchTracePort(Protocol):
    # 发送一条带追踪标识和结构化载荷的事件。
    async def emit(
        self, event_type: str, trace_id: str, payload: dict[str, Any]
    ) -> None: ...
