from __future__ import annotations

import hmac
import uuid
from typing import Any

from mcp.server.fastmcp import FastMCP
from starlette.types import ASGIApp, Receive, Scope, Send

from flowfix_agent.tools.models import ToolCall, ToolContext


class BearerAuthMiddleware:
    """为内嵌 MCP 端点提供与 HTTP API 分离的静态服务令牌。"""

    def __init__(self, app: ASGIApp, token: str | None) -> None:
        self.app = app
        self.token = token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if self.token and scope["type"] == "http":
            headers = {key.lower(): value for key, value in scope.get("headers", [])}
            supplied = headers.get(b"authorization", b"").decode("latin-1")
            scheme, _, credential = supplied.partition(" ")
            if scheme.lower() != "bearer" or not hmac.compare_digest(
                credential, self.token
            ):
                await send(
                    {
                        "type": "http.response.start",
                        "status": 401,
                        "headers": [(b"content-type", b"application/json")],
                    }
                )
                await send(
                    {
                        "type": "http.response.body",
                        "body": b'{"error":"invalid MCP authentication token"}',
                    }
                )
                return
        await self.app(scope, receive, send)


class FlowFixMCPServer:
    """把公共 Tool Gateway 的只读能力暴露为 MCP，保留相同 Policy 与 Schema 边界。"""

    def __init__(
        self,
        *,
        auth_token: str | None = None,
        allowed_tenants: set[str] | None = None,
    ) -> None:
        self._container: Any | None = None
        self.mcp = FastMCP(
            "FlowFix Agent",
            instructions="Tenant-scoped read-only equipment operations capabilities.",
            streamable_http_path="/mcp",
            stateless_http=True,
            json_response=True,
        )
        self.auth_token = auth_token
        self.allowed_tenants = allowed_tenants or {"public"}

        @self.mcp.tool(name="knowledge_search", structured_output=True)
        async def knowledge_search(
            query: str,
            tenant_id: str = "public",
            visibility: str = "public",
            scope: dict[str, Any] | None = None,
            options: dict[str, Any] | None = None,
            trace_id: str | None = None,
        ) -> dict[str, Any]:
            """Search FlowFix manuals and SOPs in the authorized tenant scope."""
            if scope is not None:
                tenant_id = str(scope.get("tenant_id", tenant_id))
                visibility = str(scope.get("visibility", visibility))
            if tenant_id not in self.allowed_tenants:
                raise PermissionError("tenant is not authorized for this MCP server")
            container = self._require_container()
            trace_id = trace_id or f"mcp-{uuid.uuid4().hex}"
            observation = await container.tool_gateway.invoke(
                ToolCall(
                    capability="knowledge.search",
                    call_id=f"{trace_id}:knowledge.search",
                    arguments={
                        "query": query,
                        "scope": {
                            "tenant_id": tenant_id,
                            "visibility": visibility,
                            "source_types": [],
                            "source_ids": [],
                        },
                        "options": options or {},
                        "trace_id": trace_id,
                    },
                ),
                ToolContext(
                    trace_id=trace_id,
                    tenant_id=tenant_id,
                    chain="qa",
                    role="mcp-client",
                    permissions={"tool:read"},
                    allowed_capabilities={"knowledge.search"},
                    max_tool_calls=1,
                ),
            )
            if not observation.success or not isinstance(observation.payload, dict):
                raise RuntimeError(observation.error_message or "knowledge search failed")
            return observation.payload

    def bind(self, container: Any) -> None:
        self._container = container

    def unbind(self) -> None:
        self._container = None

    def asgi_app(self) -> ASGIApp:
        return BearerAuthMiddleware(self.mcp.streamable_http_app(), self.auth_token)

    def _require_container(self) -> Any:
        if self._container is None:
            raise RuntimeError("MCP server is not attached to a running application")
        return self._container
