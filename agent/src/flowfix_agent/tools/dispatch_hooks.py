from __future__ import annotations

from enum import StrEnum
from typing import Any, Protocol


# Dispatch 允许的三类受控 Hook 时机。
class DispatchHookPoint(StrEnum):
    PRE_READ_ENRICHMENT = "pre_read_enrichment"
    PRE_WRITE_VALIDATION = "pre_write_validation"
    POST_WRITE_VERIFICATION = "post_write_verification"


# Dispatch Hook 协议：在指定时机异步处理并返回负载。
class DispatchHook(Protocol):
    hook_id: str
    point: DispatchHookPoint

    async def run(self, payload: dict[str, Any]) -> dict[str, Any]: ...
