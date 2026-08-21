from __future__ import annotations

from typing import Any, Protocol

from flowfix_agent.tools.models import ToolContext


# 工具 Provider 协议：暴露 provider_id，并异步执行能力调用。
class ToolProvider(Protocol):
    provider_id: str

    async def invoke(
        self, capability: str, arguments: dict[str, Any], context: ToolContext
    ) -> Any: ...
