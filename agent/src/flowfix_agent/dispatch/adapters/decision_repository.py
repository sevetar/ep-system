from __future__ import annotations

import asyncio

from flowfix_agent.dispatch.domain.models import DispatchDecision


# 提供带并发保护的内存调度决策仓库。
class InMemoryDispatchDecisionRepository:
    """供离线评测和进程内运行时使用的幂等决策仓库。"""

    # 初始化事件索引和异步互斥锁。
    def __init__(self) -> None:
        self._by_event: dict[str, DispatchDecision] = {}
        self._lock = asyncio.Lock()

    # 按事件标识读取决策，并返回隔离的深拷贝。
    async def get_by_event(self, event_id: str) -> DispatchDecision | None:
        async with self._lock:
            decision = self._by_event.get(event_id)
            return decision.model_copy(deep=True) if decision else None

    # 仅在事件尚无决策时保存，以保证幂等写入。
    async def save_if_absent(self, decision: DispatchDecision) -> DispatchDecision:
        async with self._lock:
            existing = self._by_event.get(decision.event_id)
            if existing:
                return existing.model_copy(deep=True)
            self._by_event[decision.event_id] = decision.model_copy(deep=True)
            return decision.model_copy(deep=True)
