from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from flowfix_agent.api.routes import router
from flowfix_agent.bootstrap.container import build_container
from flowfix_agent.core.config import get_settings
from flowfix_agent.core.errors import FlowFixError
from flowfix_agent.mcp_server import FlowFixMCPServer


# 管理 FastAPI 生命周期内依赖容器的启动和关闭。
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    container = build_container(settings)
    await container.start()
    app.state.container = container
    mcp_server = getattr(app.state, "mcp_server", None)
    if mcp_server is not None:
        mcp_server.bind(container)
    try:
        if mcp_server is not None:
            async with mcp_server.mcp.session_manager.run():
                yield
        else:
            yield
    finally:
        if mcp_server is not None:
            mcp_server.unbind()
        await container.close()


# 创建 FastAPI 应用并注册路由和统一异常处理器。
def create_app() -> FastAPI:
    application = FastAPI(
        title="FlowFix Agent",
        version="0.1.0",
        description="Controlled multi-chain agent service for FlowFix equipment operations",
        lifespan=lifespan,
    )
    application.include_router(router)

    # 将领域异常统一转换为结构化的 HTTP 422 响应。
    @application.exception_handler(FlowFixError)
    async def handle_domain_error(request: Request, exc: FlowFixError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"error": type(exc).__name__, "message": str(exc)},
        )

    settings = get_settings()
    if settings.mcp_server_enabled:
        mcp_server = FlowFixMCPServer(
            auth_token=(
                settings.mcp_auth_token.get_secret_value()
                if settings.mcp_auth_token
                else None
            ),
            allowed_tenants=settings.mcp_allowed_tenants,
        )
        application.state.mcp_server = mcp_server
        # FastMCP 自身保留 /mcp 路径；挂在根部可得到标准 Streamable HTTP /mcp。
        application.mount("/", mcp_server.asgi_app())

    return application


app = create_app()
