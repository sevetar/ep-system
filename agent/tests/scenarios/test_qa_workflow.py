from flowfix_agent.core.models import RequestScope
from flowfix_agent.knowledge.models import SourceType
from flowfix_agent.memory.conversation import (
    ConversationNamespace,
    ConversationService,
    SQLiteConversationStore,
)
from flowfix_agent.qa.workflow import QAWorkflow
from flowfix_agent.retrieval.models import (
    Evidence,
    EvidenceBundle,
    RetrievalMode,
)


# 模拟可记录事件的追踪端口。
class FakeTrace:
    # 初始化内存事件列表。
    def __init__(self):
        self.events = []

    # 把收到的追踪事件追加到内存列表。
    async def emit(self, event_type, trace_id, payload):
        self.events.append((event_type, trace_id, payload))


# 模拟生成固定带引用答案的生成器。
class FakeGenerator:
    model = "fake-model"

    # 初始化答案生成调用计数器。
    def __init__(self):
        self.calls = 0

    # 返回固定答案并累计生成调用次数。
    async def generate(self, question, evidence):
        self.calls += 1
        return "设备服务注册名为 service-product。[1]"

    # 为候选答案补充一个合法引用编号。
    async def repair(self, question, evidence, draft):
        return f"{draft} [1]"


# 模拟可返回充分或空证据的检索服务。
class FakeRetrieval:
    # 配置本次模拟检索是否提供充分证据。
    def __init__(self, sufficient=True):
        self.sufficient = sufficient
        self.last_query = None

    # 根据充分性开关构造模拟证据包。
    async def retrieve(self, query, scope, options, trace_id=None):
        self.last_query = query
        evidence = []
        if self.sufficient:
            evidence = [
                Evidence(
                    citation_id=1,
                    chunk_id="chunk-1",
                    source_id="PROJECT_GUIDE.md",
                    source_type=SourceType.PLATFORM_DOC,
                    source_version="v1",
                    title="Project Guide",
                    section_path="技术架构",
                    content="设备服务注册名为 service-product。",
                    score=1.0,
                    estimated_tokens=10,
                )
            ]
        return EvidenceBundle(
            trace_id=trace_id,
            original_query=query,
            retrieval_query=query,
            mode=RetrievalMode.HYBRID,
            scope=scope,
            candidates=[],
            selected_evidence=evidence,
            budget_used=10 if evidence else 0,
            sufficient=bool(evidence),
            latency_ms=1,
        )


# 验证证据充分时工作流生成答案并通过引用校验。
async def test_qa_generates_and_validates_citations():
    trace = FakeTrace()
    generator = FakeGenerator()
    workflow = QAWorkflow(FakeRetrieval(), generator, trace)

    result = await workflow.run("设备服务名是什么？", RequestScope())

    assert result.refused is False
    assert result.validation.valid is True
    assert result.citations[0].source_id == "PROJECT_GUIDE.md"
    assert generator.calls == 1
    assert [event[0] for event in trace.events] == ["qa.completed"]


# 验证证据不足时工作流拒答且不调用生成器。
async def test_qa_abstains_without_calling_generator():
    trace = FakeTrace()
    generator = FakeGenerator()
    workflow = QAWorkflow(FakeRetrieval(sufficient=False), generator, trace)

    result = await workflow.run("保修期多久？")

    assert result.refused is True
    assert result.citations == []
    assert generator.calls == 0


async def test_qa_uses_thread_memory_for_follow_up_and_finalizes(tmp_path):
    retrieval = FakeRetrieval()
    conversation = ConversationService(SQLiteConversationStore(tmp_path / "qa.db"))
    workflow = QAWorkflow(retrieval, FakeGenerator(), FakeTrace(), conversation)
    namespace = ConversationNamespace(
        tenant_id="tenant-a", user_id="user-a", thread_id="thread-a"
    )
    await workflow.run("设备 DEV-1 的手册怎么说？", conversation_namespace=namespace)

    result = await workflow.run(
        "它怎么重启？",
        conversation_namespace=namespace,
        end_conversation=True,
    )

    assert result.rewritten_question is not None
    assert "设备 DEV-1" in result.rewritten_question
    assert retrieval.last_query == result.rewritten_question
    assert result.conversation_version == 2
    assert result.conversation_finalized is True
