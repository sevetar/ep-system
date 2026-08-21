from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import httpx
from elasticsearch import AsyncElasticsearch
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.redis.aio import AsyncRedisSaver
from redis.asyncio import Redis

from flowfix_agent.adapters.catalog import FileKnowledgeCatalog
from flowfix_agent.adapters.diagnosis_generator import LangChainDiagnosisGenerator
from flowfix_agent.adapters.elasticsearch import ElasticsearchKnowledgeAdapter
from flowfix_agent.adapters.impact_safety_generator import (
    LangChainImpactSafetyGenerator,
)
from flowfix_agent.adapters.investigation_decision import (
    LangChainInvestigationDecision,
)
from flowfix_agent.adapters.models import (
    LangChainAnswerGenerator,
    OpenAICompatibleEmbeddings,
    OpenAICompatibleReranker,
)
from flowfix_agent.adapters.planning_planner import LangChainPlanningPlanner
from flowfix_agent.adapters.resource_planning_generator import (
    LangChainResourcePlanningGenerator,
)
from flowfix_agent.assistant import AssistantService
from flowfix_agent.core.config import Settings
from flowfix_agent.dispatch.adapters.java_http import JavaDispatchHttpAdapter
from flowfix_agent.dispatch.adapters.mysql_decision_repository import (
    MySQLDispatchDecisionRepository,
)
from flowfix_agent.dispatch.adapters.proposal_bridge import ProposalDispatchBridge
from flowfix_agent.dispatch.adapters.skill_registry import FileDispatchSkillRegistry
from flowfix_agent.dispatch.adapters.sqlite_decision_repository import (
    SQLiteDispatchDecisionRepository,
)
from flowfix_agent.dispatch.application.service import DispatchDecisionService
from flowfix_agent.dispatch.runtime.graph import DispatchAgentRuntime
from flowfix_agent.dispatch.runtime.middleware import DispatchToolGateway
from flowfix_agent.dispatch.skills.loader import DispatchSkillLoader
from flowfix_agent.investigation import InvestigationLoop
from flowfix_agent.knowledge.ledger import FileWorkOrderKnowledgeLedger
from flowfix_agent.knowledge.markdown import MarkdownKnowledgeLoader
from flowfix_agent.knowledge.quality import WorkOrderKnowledgeQualityGate
from flowfix_agent.knowledge.service import KnowledgeIngestionService
from flowfix_agent.knowledge.work_order import WorkOrderCaseIngestionService
from flowfix_agent.memory import (
    ConversationService,
    MySQLConversationStore,
    MySQLStoreConfig,
    MySQLTaskArtifactStore,
    SQLiteConversationStore,
    SQLiteTaskArtifactStore,
)
from flowfix_agent.messaging import RabbitDispatchBridge
from flowfix_agent.messaging.knowledge_rabbitmq import RabbitWorkOrderKnowledgeBridge
from flowfix_agent.observability.jsonl import JsonlTraceSink
from flowfix_agent.planning.completion import CompletionGate
from flowfix_agent.planning.controller import PlanController
from flowfix_agent.planning.registry import WorkerRegistry
from flowfix_agent.planning.replanning import RuleBasedReplanDetector, RuleBasedReplanner
from flowfix_agent.planning.runtime import PlanningRuntime
from flowfix_agent.planning.validation import PlanValidator
from flowfix_agent.planning.workers.diagnosis import DiagnosisWorker
from flowfix_agent.planning.workers.impact_safety import ImpactSafetyWorker
from flowfix_agent.planning.workers.resource_planning import ResourcePlanningWorker
from flowfix_agent.qa.workflow import QAWorkflow
from flowfix_agent.reliability import RedisLeaseManager
from flowfix_agent.retrieval.selector import EvidenceSelector
from flowfix_agent.retrieval.service import HybridRetrievalService
from flowfix_agent.routing import LLMRouteClassifier, RequestRouter
from flowfix_agent.tools import ToolGateway, ToolRegistry, ToolResolver
from flowfix_agent.tools.providers import (
    MCPToolProvider,
    RetrievalCapabilityClient,
    RetrievalToolProvider,
    knowledge_search_spec,
)


# 聚合应用运行期间共享的配置、客户端和业务服务实例。
@dataclass
class AppContainer:
    settings: Settings
    elasticsearch_client: AsyncElasticsearch
    model_client: httpx.AsyncClient
    catalog: FileKnowledgeCatalog
    index: ElasticsearchKnowledgeAdapter
    ingestion: KnowledgeIngestionService
    work_order_knowledge_ledger: FileWorkOrderKnowledgeLedger
    work_order_knowledge_ingestion: WorkOrderCaseIngestionService
    retrieval: HybridRetrievalService
    tool_registry: ToolRegistry
    tool_gateway: ToolGateway
    conversation: ConversationService
    task_artifacts: SQLiteTaskArtifactStore | MySQLTaskArtifactStore
    checkpointer: BaseCheckpointSaver
    request_router: RequestRouter
    qa: QAWorkflow
    planning_workers: WorkerRegistry
    planner: LangChainPlanningPlanner
    planning_runtime: PlanningRuntime
    investigation_decision: LangChainInvestigationDecision
    investigation_loop: InvestigationLoop
    assistant: AssistantService
    java_dispatch_client: httpx.AsyncClient
    java_dispatch: JavaDispatchHttpAdapter
    dispatch_runtime: DispatchAgentRuntime
    proposal_dispatch: ProposalDispatchBridge
    redis_client: Redis | None = None
    rabbitmq: RabbitDispatchBridge | None = None
    knowledge_rabbitmq: RabbitWorkOrderKnowledgeBridge | None = None

    # 创建运行目录、确保知识索引与 Redis 检查点可用。
    async def start(self) -> None:
        self.settings.resolved_runtime_dir.mkdir(parents=True, exist_ok=True)
        await self.index.ensure_index()
        if isinstance(self.checkpointer, AsyncRedisSaver):
            await self.checkpointer.asetup()
        if self.rabbitmq is not None:
            await self.rabbitmq.start()
        if self.knowledge_rabbitmq is not None:
            await self.knowledge_rabbitmq.start()

    # 依次关闭模型服务、Java 派单客户端、Redis 检查点和 Elasticsearch 异步客户端。
    async def close(self) -> None:
        await self.model_client.aclose()
        await self.java_dispatch_client.aclose()
        if isinstance(self.checkpointer, AsyncRedisSaver):
            await self.checkpointer.__aexit__(None, None, None)
        if self.rabbitmq is not None:
            await self.rabbitmq.close()
        if self.knowledge_rabbitmq is not None:
            await self.knowledge_rabbitmq.close()
        if self.redis_client is not None:
            await self.redis_client.aclose()
        await self.elasticsearch_client.close()


# 根据应用配置集中创建并装配所有外部适配器和业务服务。
def build_container(settings: Settings) -> AppContainer:
    credentials = settings.model_credentials()
    api_key = credentials.api_key.get_secret_value()
    model_client = httpx.AsyncClient(
        base_url=f"{credentials.base_url.rstrip('/')}/",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=settings.model_timeout_seconds,
    )
    elasticsearch_client = AsyncElasticsearch(settings.elasticsearch_url)
    catalog = FileKnowledgeCatalog(settings.resolved_runtime_dir / "catalog.json")
    trace = JsonlTraceSink(settings.resolved_runtime_dir / "traces.jsonl")
    index = ElasticsearchKnowledgeAdapter(
        elasticsearch_client,
        settings.elasticsearch_index,
        settings.embedding_dimensions,
    )
    embedding = OpenAICompatibleEmbeddings(
        model_client,
        settings.embedding_model,
        settings.embedding_dimensions,
    )
    reranker = OpenAICompatibleReranker(model_client, settings.rerank_model)
    loader = MarkdownKnowledgeLoader(
        settings.resolved_knowledge_root,
        settings.chunk_size,
        settings.chunk_overlap,
    )
    ingestion = KnowledgeIngestionService(
        loader,
        embedding,
        index,
        catalog,
        trace,
        settings.embedding_batch_size,
    )
    work_order_knowledge_ledger = FileWorkOrderKnowledgeLedger(
        settings.resolved_runtime_dir / "work-order-knowledge-ledger.json"
    )
    work_order_knowledge_ingestion = WorkOrderCaseIngestionService(
        ingestion,
        work_order_knowledge_ledger,
        WorkOrderKnowledgeQualityGate(),
        catalog,
        index,
        trace,
    )
    selector = EvidenceSelector(
        settings.evidence_token_budget,
        settings.final_top_k,
        settings.vector_min_score,
        settings.rerank_min_score,
    )
    retrieval = HybridRetrievalService(
        index,
        catalog,
        embedding,
        selector,
        trace,
        reranker,
        settings.bm25_top_k,
        settings.vector_top_k,
        settings.rrf_k,
        settings.rerank_enabled,
    )
    generator = LangChainAnswerGenerator(
        api_key,
        credentials.base_url,
        settings.chat_model,
        settings.model_timeout_seconds,
    )
    # 工具平台：先注册本地 Provider 作为 knowledge.search 的默认实现。
    tool_registry = ToolRegistry()
    knowledge_spec = knowledge_search_spec()
    tool_registry.register(knowledge_spec, RetrievalToolProvider(retrieval))
    # 显式配置远端 MCP 且其声明包含该 capability 时，用 MCP 实现覆盖同名 spec。
    if settings.mcp_remote_url and "knowledge.search" in settings.mcp_remote_capabilities:
        tool_registry.register(
            knowledge_spec,
            MCPToolProvider(
                settings.mcp_remote_url,
                settings.mcp_remote_capabilities,
                token=(
                    settings.mcp_remote_token.get_secret_value()
                    if settings.mcp_remote_token
                    else None
                ),
                timeout_seconds=settings.mcp_timeout_seconds,
            ),
            # 显式配置远端 MCP 后，远端是该 capability 的首选实现；
            # Resolver 仍允许 preferred_provider 定向回退到本地 Provider。
            priority=50,
        )
    tool_gateway = ToolGateway(ToolResolver(tool_registry))
    if settings.store_backend == "mysql":
        store_config = MySQLStoreConfig(
            host=settings.mysql_host,
            port=settings.mysql_port,
            user=settings.mysql_user,
            password=(
                settings.mysql_password.get_secret_value()
                if settings.mysql_password
                else None
            ),
            database=settings.mysql_database,
        )
        conversation_store = MySQLConversationStore(store_config)
        task_artifacts = MySQLTaskArtifactStore(store_config)
        decision_repository = MySQLDispatchDecisionRepository(store_config)
    else:
        conversation_store = SQLiteConversationStore(
            settings.resolved_runtime_dir / "conversation.sqlite3"
        )
        task_artifacts = SQLiteTaskArtifactStore(
            settings.resolved_runtime_dir / "task-artifacts.sqlite3"
        )
        decision_repository = SQLiteDispatchDecisionRepository(
            settings.resolved_runtime_dir / "dispatch-decisions.sqlite3"
        )
    conversation = ConversationService(
        conversation_store,
        ttl_hours=settings.conversation_ttl_hours,
        recent_limit=settings.conversation_recent_limit,
    )
    retrieval_capability = RetrievalCapabilityClient(tool_gateway)
    qa = QAWorkflow(retrieval_capability, generator, trace, conversation)
    diagnosis_worker = DiagnosisWorker(
        retrieval_capability,
        LangChainDiagnosisGenerator(
            api_key,
            credentials.base_url,
            settings.chat_model,
            settings.model_timeout_seconds,
        ),
        max_queries=settings.diagnosis_max_queries,
    )
    impact_safety_worker = ImpactSafetyWorker(
        retrieval_capability,
        LangChainImpactSafetyGenerator(
            api_key,
            credentials.base_url,
            settings.chat_model,
            settings.model_timeout_seconds,
        ),
        max_queries=settings.impact_safety_max_queries,
    )
    resource_planning_worker = ResourcePlanningWorker(
        retrieval_capability,
        LangChainResourcePlanningGenerator(
            api_key,
            credentials.base_url,
            settings.chat_model,
            settings.model_timeout_seconds,
        ),
        max_queries=settings.resource_planning_max_queries,
    )
    planning_workers = WorkerRegistry()
    planning_workers.register("diagnosis", diagnosis_worker)
    planning_workers.register("impact_safety", impact_safety_worker)
    planning_workers.register("resource_planning", resource_planning_worker)
    route_classifier = None
    if settings.router_llm_fallback_enabled:
        route_classifier = LLMRouteClassifier(
            api_key,
            credentials.base_url,
            settings.chat_model,
            settings.model_timeout_seconds,
        )
    request_router = RequestRouter(route_classifier)
    java_dispatch_client = httpx.AsyncClient(
        base_url=f"{settings.java_dispatch_base_url.rstrip('/')}/",
        timeout=settings.java_dispatch_timeout_seconds,
    )
    java_dispatch = JavaDispatchHttpAdapter(
        java_dispatch_client,
        settings.resolved_runtime_dir / "dispatch-audit.jsonl",
    )
    registry = FileDispatchSkillRegistry(
        settings.resolved_runtime_dir / "dispatch-skills.json"
    )
    builtin_path = (
        Path(__file__).resolve().parents[1] / "dispatch" / "skills" / "builtin"
    )
    for skill in DispatchSkillLoader().load_directory(builtin_path):
        registry.register(skill)
    registry.activate("balanced", "1.0.0")
    checkpointer: BaseCheckpointSaver = InMemorySaver()
    if settings.redis_checkpoint_enabled and settings.redis_url:
        checkpointer = AsyncRedisSaver(redis_url=settings.redis_url)
    dispatch_runtime = DispatchAgentRuntime(
        DispatchDecisionService(registry, decision_repository, trace),
        DispatchToolGateway(
            java_dispatch,
            timeout_seconds=settings.dispatch_tool_timeout_seconds,
        ),
        checkpointer=checkpointer,
    )
    # 调查链派单建议的强制人工审批转交边界：只读校验失败即拒绝，不触碰 Java。
    proposal_dispatch = ProposalDispatchBridge(
        dispatch_runtime,
        execution_timeout_seconds=settings.dispatch_execution_timeout_seconds,
        approval_ttl_seconds=settings.dispatch_approval_ttl_seconds,
    )
    # 生产规划器：将事故上下文分解为通过 PlanValidator 校验的只读任务 DAG。
    planner = LangChainPlanningPlanner(
        api_key,
        credentials.base_url,
        settings.chat_model,
        settings.model_timeout_seconds,
    )
    # 链三规划控制面：固定五节点 StateGraph，含内容触发 Replan 与完成门禁。
    planning_runtime = PlanningRuntime(
        planner,
        PlanController(task_artifacts, PlanValidator()),
        planning_workers,
        task_artifacts,
        RuleBasedReplanner(),
        RuleBasedReplanDetector(),
        CompletionGate(required_roles=set(settings.completion_required_roles)),
        max_replans=settings.max_replans,
        checkpointer=checkpointer,
    )
    # 生产调查决策端：驱动单 Agent 只读调查循环。
    investigation_decision = LangChainInvestigationDecision(
        api_key,
        credentials.base_url,
        settings.chat_model,
        settings.model_timeout_seconds,
    )
    investigation_loop = InvestigationLoop(
        investigation_decision,
        tool_registry,
        tool_gateway,
    )
    # 统一入口编排服务：Router 只选链路，本服务按路由结果转调目标运行时。
    assistant = AssistantService(
        request_router,
        qa,
        dispatch_runtime,
        planning_runtime,
        proposal_dispatch,
        conversation,
        settings,
        investigation_loop,
    )
    redis_client = None
    rabbitmq = None
    knowledge_rabbitmq = None
    if settings.rabbitmq_enabled or settings.work_order_knowledge_enabled:
        if not settings.redis_url:
            raise ValueError("RabbitMQ consumers require REDIS_URL for distributed leases")
        redis_client = Redis.from_url(settings.redis_url, decode_responses=True)
    if settings.rabbitmq_enabled:
        assert redis_client is not None
        rabbitmq = RabbitDispatchBridge(
            settings.rabbitmq_url,
            dispatch_runtime,
            RedisLeaseManager(redis_client),
            instance_id=settings.instance_id,
            retry_delay_ms=settings.rabbitmq_retry_delay_ms,
            max_retries=settings.rabbitmq_max_retries,
            approval_ttl_seconds=settings.dispatch_approval_ttl_seconds,
        )
    if settings.work_order_knowledge_enabled:
        assert redis_client is not None
        knowledge_rabbitmq = RabbitWorkOrderKnowledgeBridge(
            settings.rabbitmq_url,
            work_order_knowledge_ingestion,
            RedisLeaseManager(redis_client),
            instance_id=settings.instance_id,
            retry_delay_ms=settings.rabbitmq_retry_delay_ms,
            max_retries=settings.rabbitmq_max_retries,
        )
    return AppContainer(
        settings=settings,
        elasticsearch_client=elasticsearch_client,
        model_client=model_client,
        catalog=catalog,
        index=index,
        ingestion=ingestion,
        work_order_knowledge_ledger=work_order_knowledge_ledger,
        work_order_knowledge_ingestion=work_order_knowledge_ingestion,
        retrieval=retrieval,
        tool_registry=tool_registry,
        tool_gateway=tool_gateway,
        conversation=conversation,
        task_artifacts=task_artifacts,
        checkpointer=checkpointer,
        request_router=request_router,
        qa=qa,
        planning_workers=planning_workers,
        planner=planner,
        planning_runtime=planning_runtime,
        investigation_decision=investigation_decision,
        investigation_loop=investigation_loop,
        assistant=assistant,
        java_dispatch_client=java_dispatch_client,
        java_dispatch=java_dispatch,
        dispatch_runtime=dispatch_runtime,
        proposal_dispatch=proposal_dispatch,
        redis_client=redis_client,
        rabbitmq=rabbitmq,
        knowledge_rabbitmq=knowledge_rabbitmq,
    )
