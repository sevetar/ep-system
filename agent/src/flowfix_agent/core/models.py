from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


# 描述一次请求允许访问的租户、设备和知识源范围。
class RequestScope(BaseModel):
    tenant_id: str = Field(default="public", min_length=1, max_length=128)
    visibility: Literal["public", "tenant"] = "public"
    device_category: str | None = None
    device_model: str | None = None
    source_types: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)


# 由认证边界建立的可信调用者上下文；业务请求正文不得覆盖这些权威字段。
class Principal(BaseModel):
    user_id: str = Field(min_length=1, max_length=128)
    tenant_id: str = Field(min_length=1, max_length=128)
    permissions: frozenset[str] = Field(default_factory=frozenset)
