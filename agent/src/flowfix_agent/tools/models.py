from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


# 能力访问级别：只读、只写与审计。
class CapabilityAccess(StrEnum):
    READ = "read"
    WRITE = "write"
    AUDIT = "audit"


# 能力的声明合同：名称、版本、描述、访问级别与输入/输出 Schema。
class ToolSpec(BaseModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9_.-]+$")
    version: str = Field(min_length=1)
    description: str
    access: CapabilityAccess = CapabilityAccess.READ
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    # 该能力单次观察的上限字符数；未设置时沿用网关默认裁剪上限。
    max_observation_chars: int | None = None


# 一次工具调用请求：目标能力、参数与调用标识。
class ToolCall(BaseModel):
    capability: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    call_id: str


# 工具调用上下文：链路、角色、权限、允许的能力与调用预算。
class ToolContext(BaseModel):
    trace_id: str
    tenant_id: str
    chain: Literal["qa", "dispatch", "investigation"]
    role: str
    permissions: set[str] = Field(default_factory=set)
    allowed_capabilities: set[str] = Field(default_factory=set)
    max_tool_calls: int = Field(default=6, ge=1, le=100)


# 一次工具调用的结果：成功与否、负载、错误、裁剪与延迟。
class ToolObservation(BaseModel):
    call_id: str
    capability: str
    provider: str
    success: bool
    payload: Any | None = None
    error_code: str | None = None
    error_message: str | None = None
    truncated: bool = False
    untrusted: bool = True
    latency_ms: float = 0
