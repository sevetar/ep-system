from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from flowfix_agent.tools.models import ToolContext


# 契约测试替身，并非真实的 MCP 网络服务/客户端。
class FakeMCPProvider:
    provider_id = "fake-mcp"

    # 绑定能力名到异步处理函数的映射表。
    def __init__(
        self,
        handlers: dict[
            str, Callable[[dict[str, Any], ToolContext], Awaitable[Any]]
        ],
    ) -> None:
        self.handlers = handlers

    # 调用对应能力处理器。
    async def invoke(
        self, capability: str, arguments: dict[str, Any], context: ToolContext
    ) -> Any:
        return await self.handlers[capability](arguments, context)
