from __future__ import annotations

from flowfix_agent.tools.errors import ToolAuthorizationError
from flowfix_agent.tools.models import CapabilityAccess, ToolContext, ToolSpec


# 调用授权策略：校验能力可见性、读写权限与 Investigation 只读约束。
class ToolPolicy:
    # 校验上下文是否被允许调用该能力，不通过时抛出 ToolAuthorizationError。
    def authorize(self, spec: ToolSpec, context: ToolContext) -> None:
        if spec.name not in context.allowed_capabilities:
            raise ToolAuthorizationError(
                f"capability is not visible to {context.chain}/{context.role}: {spec.name}"
            )
        required = f"tool:{spec.access.value}"
        if required not in context.permissions:
            raise ToolAuthorizationError(f"request lacks permission {required}")
        if context.chain == "investigation" and spec.access is not CapabilityAccess.READ:
            raise ToolAuthorizationError("investigation capabilities must be read-only")
