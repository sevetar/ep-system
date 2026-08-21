from types import SimpleNamespace

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.server.fastmcp.exceptions import ToolError

from flowfix_agent.mcp_server import FlowFixMCPServer
from flowfix_agent.tools.models import ToolObservation


class FakeGateway:
    def __init__(self):
        self.calls = []

    async def invoke(self, call, context):
        self.calls.append((call, context))
        return ToolObservation(
            call_id=call.call_id,
            capability=call.capability,
            provider="fake",
            success=True,
            payload={
                "trace_id": call.arguments["trace_id"],
                "selected_evidence": [],
                "sufficient": False,
            },
        )


async def test_mcp_server_exposes_gateway_backed_read_only_search():
    gateway = FakeGateway()
    server = FlowFixMCPServer(allowed_tenants={"tenant-1"})
    server.bind(SimpleNamespace(tool_gateway=gateway))

    result = await server.mcp.call_tool(
        "knowledge_search",
        {"query": "锁冲突", "tenant_id": "tenant-1", "visibility": "tenant"},
    )

    _, structured = result
    assert structured["sufficient"] is False
    call, context = gateway.calls[0]
    assert call.capability == "knowledge.search"
    assert context.permissions == {"tool:read"}
    assert context.allowed_capabilities == {"knowledge.search"}
    assert context.tenant_id == "tenant-1"


async def test_mcp_server_rejects_tenant_outside_static_allowlist():
    server = FlowFixMCPServer(allowed_tenants={"public"})
    server.bind(SimpleNamespace(tool_gateway=FakeGateway()))

    with pytest.raises(ToolError, match="not authorized"):
        await server.mcp.call_tool(
            "knowledge_search", {"query": "x", "tenant_id": "tenant-secret"}
        )


async def test_mcp_streamable_http_protocol_and_bearer_auth():
    server = FlowFixMCPServer(auth_token="secret")
    server.bind(SimpleNamespace(tool_gateway=FakeGateway()))
    transport = httpx.ASGITransport(app=server.asgi_app())

    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost:8000"
    ) as unauthorized:
        response = await unauthorized.post("/mcp", json={})
        assert response.status_code == 401

    async with server.mcp.session_manager.run():
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://localhost:8000",
            headers={"Authorization": "Bearer secret"},
        ) as authorized:
            async with streamable_http_client(
                "http://localhost:8000/mcp", http_client=authorized
            ) as (read_stream, write_stream, _):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    result = await session.call_tool("knowledge_search", {"query": "x"})

    assert [tool.name for tool in tools.tools] == ["knowledge_search"]
    assert result.structuredContent["sufficient"] is False
