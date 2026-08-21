from __future__ import annotations

from flowfix_agent.tools.registry import ProviderRegistration, ToolRegistry


# 能力解析器：从注册表中选择具体 Provider，支持按首选 Provider 定向。
class ToolResolver:
    # 绑定能力注册表。
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    # 解析能力对应的注册项，优先返回指定 provider，否则取优先级最高者。
    def resolve(
        self, capability: str, *, preferred_provider: str | None = None
    ) -> ProviderRegistration:
        registrations = self.registry.registrations(capability)
        if preferred_provider:
            for registration in registrations:
                if registration.provider.provider_id == preferred_provider:
                    return registration
        return registrations[0]
