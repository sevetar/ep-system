from __future__ import annotations

import hmac

from fastapi import HTTPException, Request, status

from flowfix_agent.core.models import Principal

LOCAL_PERMISSIONS = frozenset(
    {
        "knowledge:write",
        "knowledge:read",
        "knowledge:admin",
        "dispatch:read",
        "dispatch:write",
        "dispatch:approve",
        "dispatch:audit",
        "planning:read",
        "planning:write",
    }
)


# 验证可信网关令牌后，从受保护请求头建立权威 Principal。
def get_principal(request: Request) -> Principal:
    container = request.app.state.container
    settings = getattr(container, "settings", None)
    configured = getattr(settings, "api_auth_token", None)
    expected = configured.get_secret_value() if configured else None
    if expected:
        authorization = request.headers.get("Authorization", "")
        scheme, _, supplied = authorization.partition(" ")
        if scheme.lower() != "bearer" or not hmac.compare_digest(supplied, expected):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid API authentication token",
            )
    app_env = getattr(settings, "app_env", "test")
    if app_env == "production" and not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="production API authentication is not configured",
        )
    default_permissions = LOCAL_PERMISSIONS if app_env in {"local", "test"} else frozenset()
    raw_permissions = request.headers.get("X-Principal-Permissions")
    permissions = (
        frozenset(item.strip() for item in raw_permissions.split(",") if item.strip())
        if raw_permissions is not None
        else default_permissions
    )
    return Principal(
        user_id=request.headers.get("X-Principal-Id", "local-user"),
        tenant_id=request.headers.get("X-Tenant-Id", "public"),
        permissions=permissions,
    )


def require_permission(principal: Principal, permission: str) -> None:
    if permission not in principal.permissions:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"principal lacks required permission: {permission}",
        )
