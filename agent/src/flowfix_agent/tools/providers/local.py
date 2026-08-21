from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from flowfix_agent.tools.models import ToolContext


# 本地函数 Provider：将能力名映射到内存中的异步处理器。
class LocalFunctionProvider:
    provider_id = "local-function"

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
