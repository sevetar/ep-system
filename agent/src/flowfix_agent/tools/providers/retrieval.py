from __future__ import annotations

from typing import Any

from flowfix_agent.core.models import RequestScope
from flowfix_agent.retrieval.models import EvidenceBundle, RetrievalOptions
from flowfix_agent.retrieval.service import HybridRetrievalService
from flowfix_agent.tools.errors import ToolExecutionError
from flowfix_agent.tools.gateway import ToolGateway
from flowfix_agent.tools.models import ToolCall, ToolContext, ToolSpec

KNOWLEDGE_SEARCH = "knowledge.search"


# 返回 knowledge.search 能力的声明合同（1.0.0）。
def knowledge_search_spec() -> ToolSpec:
    return ToolSpec(
        name=KNOWLEDGE_SEARCH,
        version="1.0.0",
        description="Search tenant-scoped FlowFix knowledge and return an EvidenceBundle.",
        # EvidenceBundle 含全部候选与选中证据，JSON 体积远超通用 16K 上限，
        # 按能力声明更大的观察上限，避免结构化负载被裁剪后无法还原。
        max_observation_chars=200_000,
        input_schema={
            "type": "object",
            "required": ["query", "scope", "options", "trace_id"],
            "properties": {
                "query": {"type": "string"},
                "scope": {"type": "object"},
                "options": {"type": "object"},
                "trace_id": {"type": "string"},
            },
        },
        output_schema={
            "type": "object",
            "required": ["trace_id", "selected_evidence", "sufficient"],
        },
    )


# 检索 Provider：把 knowledge.search 映射到混合检索服务并校验租户。
class RetrievalToolProvider:
    provider_id = "local-retrieval"

    # 绑定混合检索服务。
    def __init__(self, retrieval: HybridRetrievalService) -> None:
        self.retrieval = retrieval

    # 校验能力与租户后执行检索并返回 EvidenceBundle JSON。
    async def invoke(
        self, capability: str, arguments: dict[str, Any], context: ToolContext
    ) -> Any:
        if capability != KNOWLEDGE_SEARCH:
            raise ValueError(f"unsupported capability: {capability}")
        scope = RequestScope.model_validate(arguments["scope"])
        if scope.tenant_id != context.tenant_id:
            raise ValueError("knowledge scope tenant does not match tool context")
        bundle = await self.retrieval.retrieve(
            arguments["query"],
            scope,
            RetrievalOptions.model_validate(arguments["options"]),
            trace_id=arguments["trace_id"],
        )
        return bundle.model_dump(mode="json")


# 检索端口适配器：保持检索端口形状，同时强制走共享网关。
class RetrievalCapabilityClient:
    # 绑定统一工具网关。
    def __init__(self, gateway: ToolGateway) -> None:
        self.gateway = gateway

    # 通过网关以只读权限调用 knowledge.search 并还原 EvidenceBundle。
    # 默认使用 QA 链路权限；Investigation 可显式传入 investigation 链路角色。
    async def retrieve(
        self,
        query: str,
        scope: RequestScope,
        options: RetrievalOptions,
        trace_id: str | None = None,
        *,
        chain: str = "qa",
        role: str = "qa-workflow",
        max_tool_calls: int = 1,
    ) -> EvidenceBundle:
        # 未显式传 trace_id 时兜底为固定标识，保证同一次检索内工具调用与观察均可归因。
        resolved_trace = trace_id or "qa-retrieval"
        # 经共享网关以只读权限调用 knowledge.search：网关负责解析、授权、预算、超时与重试。
        observation = await self.gateway.invoke(
            ToolCall(
                capability=KNOWLEDGE_SEARCH,
                arguments={
                    "query": query,
                    "scope": scope.model_dump(mode="json"),
                    "options": options.model_dump(mode="json"),
                    "trace_id": resolved_trace,
                },
                call_id=f"{resolved_trace}:knowledge.search",
            ),
            ToolContext(
                trace_id=resolved_trace,
                tenant_id=scope.tenant_id,
                chain=chain,
                role=role,
                permissions={"tool:read"},
                allowed_capabilities={KNOWLEDGE_SEARCH},
                max_tool_calls=max_tool_calls,
            ),
        )
        # 负载被网关裁剪后无法还原为 EvidenceBundle：直接给出明确错误，
        # 而不是把 {"truncated_text": ...} 交给模型校验造成难懂的崩溃。
        if observation.truncated:
            raise ToolExecutionError(
                "knowledge.search 观察负载超出裁剪上限，无法还原 EvidenceBundle；"
                "请提高该能力的 max_observation_chars"
            )
        return EvidenceBundle.model_validate(observation.payload)
