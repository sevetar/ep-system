from flowfix_agent.core.models import RequestScope
from flowfix_agent.retrieval.models import EvidenceBundle, RetrievalMode, RetrievalOptions
from flowfix_agent.tools import ToolGateway, ToolRegistry, ToolResolver
from flowfix_agent.tools.models import ToolContext
from flowfix_agent.tools.providers import (
    RetrievalCapabilityClient,
    RetrievalToolProvider,
    knowledge_search_spec,
)


# 返回空证据包的确定性检索桩。
class StubRetrieval:
    async def retrieve(self, query, scope, options, trace_id=None):
        return EvidenceBundle(
            trace_id=trace_id or "t",
            original_query=query,
            retrieval_query=query,
            mode=RetrievalMode.HYBRID,
            scope=scope,
            candidates=[],
            selected_evidence=[],
            budget_used=0,
            sufficient=False,
            latency_ms=0.0,
        )


# 记录每次工具调用上下文的检索 Provider。
class CapturingProvider(RetrievalToolProvider):
    def __init__(self, retrieval) -> None:
        super().__init__(retrieval)
        self.contexts: list[ToolContext] = []

    async def invoke(self, capability, arguments, context):
        self.contexts.append(context)
        return await super().invoke(capability, arguments, context)


# 装配真实网关与客户端，返回可记录调用链路的客户端。
def _build_client() -> tuple[RetrievalCapabilityClient, CapturingProvider]:
    provider = CapturingProvider(StubRetrieval())
    registry = ToolRegistry()
    registry.register(knowledge_search_spec(), provider)
    client = RetrievalCapabilityClient(ToolGateway(ToolResolver(registry)))
    return client, provider


# 验证默认调用保持 QA 链路权限，QA 路径行为不变。
async def test_client_defaults_to_qa_chain():
    client, provider = _build_client()

    await client.retrieve("查询", RequestScope(tenant_id="tenant-1"), RetrievalOptions())

    context = provider.contexts[0]
    assert context.chain == "qa"
    assert context.role == "qa-workflow"
    assert context.permissions == {"tool:read"}


# 验证 Investigation 可显式切换链路角色，只读权限保持不变。
async def test_client_supports_investigation_chain():
    client, provider = _build_client()

    await client.retrieve(
        "查询",
        RequestScope(tenant_id="tenant-1"),
        RetrievalOptions(),
        trace_id="diag-1",
        chain="investigation",
        role="diagnosis-worker",
    )

    context = provider.contexts[0]
    assert context.chain == "investigation"
    assert context.role == "diagnosis-worker"
    assert context.permissions == {"tool:read"}
    assert context.allowed_capabilities == {"knowledge.search"}
