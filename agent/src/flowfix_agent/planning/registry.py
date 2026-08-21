from __future__ import annotations

from flowfix_agent.planning.ports import WorkerCapability


# Worker 注册表：按 required_role 注册与解析 Worker 能力。
class WorkerRegistry:
    # 初始化空的角色到 Worker 映射。
    def __init__(self) -> None:
        self._workers: dict[str, WorkerCapability] = {}

    # 注册角色对应 Worker，重复注册抛错。
    def register(self, role: str, worker: WorkerCapability) -> None:
        if role in self._workers:
            raise ValueError(f"worker role already registered: {role}")
        self._workers[role] = worker

    # 按角色解析 Worker，角色不存在抛 KeyError。
    def resolve(self, role: str) -> WorkerCapability:
        if role not in self._workers:
            raise KeyError(f"worker role unavailable: {role}")
        return self._workers[role]
