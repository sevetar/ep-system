from __future__ import annotations

from dataclasses import dataclass

from flowfix_agent.tools.errors import CapabilityNotFoundError
from flowfix_agent.tools.models import ToolSpec
from flowfix_agent.tools.ports import ToolProvider


# 能力注册项：声明合同、具体 Provider 与解析优先级。
@dataclass(frozen=True)
class ProviderRegistration:
    spec: ToolSpec
    provider: ToolProvider
    priority: int


# 能力注册表，按能力名聚合多个 Provider 并按优先级排序。
class ToolRegistry:
    # 初始化空的能力注册表。
    def __init__(self) -> None:
        self._registrations: dict[str, list[ProviderRegistration]] = {}

    # 注册一个能力实现，重复 Provider 会抛错，新条目按优先级插入。
    def register(
        self, spec: ToolSpec, provider: ToolProvider, *, priority: int = 100
    ) -> None:
        entries = self._registrations.setdefault(spec.name, [])
        if any(item.provider.provider_id == provider.provider_id for item in entries):
            raise ValueError(f"provider already registered: {spec.name}/{provider.provider_id}")
        entries.append(ProviderRegistration(spec, provider, priority))
        entries.sort(key=lambda item: item.priority)

    # 返回某能力的所有注册项，能力不存在时抛出 CapabilityNotFoundError。
    def registrations(self, capability: str) -> tuple[ProviderRegistration, ...]:
        entries = self._registrations.get(capability)
        if not entries:
            raise CapabilityNotFoundError(f"unknown capability: {capability}")
        return tuple(entries)

    # 返回各能力默认（优先级最高）注册项的声明合同。
    def specs(self) -> list[ToolSpec]:
        return [entries[0].spec for entries in self._registrations.values()]
