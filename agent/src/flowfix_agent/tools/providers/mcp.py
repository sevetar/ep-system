from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from flowfix_agent.tools.errors import ToolExecutionError
from flowfix_agent.tools.models import ToolContext


class MCPToolProvider:
    """真实 Streamable HTTP MCP Client；本地能力到远端 tool 的映射必须静态配置。"""

    def __init__(
        self,
        url: str,
        capability_mapping: dict[str, str],
        *,
        token: str | None = None,
        timeout_seconds: float = 10,
        provider_id: str = "mcp-http",
    ) -> None:
        self.url = url
        self.capability_mapping = dict(capability_mapping)
        self.timeout_seconds = timeout_seconds
        self.provider_id = provider_id
        self._headers = {"Authorization": f"Bearer {token}"} if token else {}

    async def invoke(
        self, capability: str, arguments: dict[str, Any], context: ToolContext
    ) -> Any:
        tool_name = self.capability_mapping.get(capability)
        if tool_name is None:
            raise ToolExecutionError(f"MCP capability is not statically mapped: {capability}")
        async with httpx.AsyncClient(
            headers=self._headers, timeout=self.timeout_seconds
        ) as client:
            async with streamable_http_client(self.url, http_client=client) as streams:
                read_stream, write_stream, _ = streams
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    result = await session.call_tool(
                        tool_name,
                        arguments,
                        read_timeout_seconds=timedelta(seconds=self.timeout_seconds),
                        meta={
                            "trace_id": context.trace_id,
                            "tenant_id": context.tenant_id,
                        },
                    )
        if result.isError:
            raise ToolExecutionError(f"MCP tool returned an error: {tool_name}")
        if result.structuredContent is not None:
            return result.structuredContent
        texts = [item.text for item in result.content if getattr(item, "type", None) == "text"]
        if not texts:
            raise ToolExecutionError(f"MCP tool returned no structured/text content: {tool_name}")
        joined = "\n".join(texts)
        try:
            return json.loads(joined)
        except json.JSONDecodeError:
            return {"text": joined}
