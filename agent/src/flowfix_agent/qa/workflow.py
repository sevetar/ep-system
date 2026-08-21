from __future__ import annotations

import time
import uuid
from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from flowfix_agent.core.errors import CitationValidationError
from flowfix_agent.core.models import RequestScope
from flowfix_agent.knowledge.ports import TracePort
from flowfix_agent.memory.conversation import (
    ConversationNamespace,
    ConversationService,
    PreparedConversation,
)
from flowfix_agent.qa.models import Citation, QAResult, ValidationResult
from flowfix_agent.qa.ports import AnswerGeneratorPort
from flowfix_agent.qa.validation import validate_citations
from flowfix_agent.retrieval.models import EvidenceBundle, RetrievalOptions
from flowfix_agent.tools.providers.retrieval import RetrievalCapabilityClient


# 描述 LangGraph 问答工作流各节点共享和补充的状态字段。
class QAState(TypedDict, total=False):
    trace_id: str
    question: str
    scope: RequestScope
    options: RetrievalOptions
    retrieval: EvidenceBundle
    answer: str
    refused: bool
    validation: ValidationResult


# 编排检索、生成、拒答和引用校验组成的受控问答状态图。
class QAWorkflow:
    # 注入检索服务、生成端口、追踪与多轮会话依赖，并编译 LangGraph 状态图。
    def __init__(
        self,
        retrieval: RetrievalCapabilityClient,
        generator: AnswerGeneratorPort,
        trace: TracePort,
        conversation: ConversationService | None = None,
    ) -> None:
        self.retrieval = retrieval
        self.generator = generator
        self.trace = trace
        self.conversation = conversation
        graph = StateGraph(QAState)
        graph.add_node("retrieve", self._retrieve)
        graph.add_node("generate", self._generate)
        graph.add_node("abstain", self._abstain)
        graph.add_node("validate", self._validate)
        graph.add_edge(START, "retrieve")
        graph.add_conditional_edges(
            "retrieve",
            self._route_after_retrieval,
            {"generate": "generate", "abstain": "abstain"},
        )
        graph.add_edge("generate", "validate")
        graph.add_edge("validate", END)
        graph.add_edge("abstain", END)
        self.graph = graph.compile()

    # 执行一次完整问答并组装可追踪的结构化结果。
    async def run(
        self,
        question: str,
        scope: RequestScope | None = None,
        options: RetrievalOptions | None = None,
        conversation_namespace: ConversationNamespace | None = None,
        end_conversation: bool = False,
        trace_id: str | None = None,
    ) -> QAResult:
        """执行一次完整问答并返回可追踪的结构化结果。

        按 retrieve → generate/abstain → validate 的固定状态图执行：检索证据不足时
        直接拒答；引用校验失败会触发一次修复重试，仍失败则抛 CitationValidationError。

        参数:
            question: 用户原始问题；开启会话且命中历史改写时，实际检索用重写后的问题。
            scope: 请求作用域，决定租户隔离与权限边界，缺省为 public。
            options: 检索选项（top_k、融合/证据选择策略），缺省使用默认配置。
            conversation_namespace: 多轮会话命名空间；提供时先合并会话历史重写问题，
                结束后把本轮问答与引用写入会话记录。
            end_conversation: 本轮是否为会话最后一轮；True 时会话生成终结摘要并落库。
            trace_id: 追踪 ID；未传入时自动生成，保证检索、生成、落库全链路可追踪。

        返回:
            QAResult: 含答案、引用列表、检索证据、校验结果、生成模型，以及可选
            的会话版本号与终结标记。
        """
        trace_id = trace_id or uuid.uuid4().hex
        started = time.perf_counter()
        prepared: PreparedConversation | None = None
        effective_question = question
        if self.conversation and conversation_namespace:
            prepared = self.conversation.prepare(conversation_namespace, question)
            effective_question = prepared.rewritten_query
        result = await self.graph.ainvoke(
            {
                "trace_id": trace_id,
                "question": effective_question,
                "scope": scope or RequestScope(),
                "options": options or RetrievalOptions(),
            }
        )
        retrieval = result["retrieval"]
        validation = result.get("validation") or ValidationResult(valid=True)
        cited = set(validation.cited_ids)
        citations = [
            Citation(
                citation_id=item.citation_id,
                source_id=item.source_id,
                title=item.title,
                section_path=item.section_path,
                source_version=item.source_version,
                chunk_id=item.chunk_id,
            )
            for item in retrieval.selected_evidence
            if item.citation_id in cited
        ]
        qa_result = QAResult(
            trace_id=trace_id,
            question=question,
            answer=result["answer"],
            refused=result.get("refused", False),
            citations=citations,
            evidence=retrieval.selected_evidence,
            retrieval=retrieval,
            validation=validation,
            generator_model=self.generator.model,
            rewritten_question=effective_question if effective_question != question else None,
        )
        if self.conversation and prepared:
            conversation_state = self.conversation.record_turn(
                prepared,
                qa_result.answer,
                citations=[citation.source_id for citation in qa_result.citations],
                end_conversation=end_conversation,
            )
            qa_result.conversation_version = conversation_state.version
            qa_result.conversation_finalized = conversation_state.final_summary is not None
        await self.trace.emit(
            "qa.completed",
            trace_id,
            {
                "question": question,
                "refused": qa_result.refused,
                "citation_ids": validation.cited_ids,
                "validation": validation.model_dump(mode="json"),
                "generator_model": self.generator.model,
                "answer_length": len(qa_result.answer),
                "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            },
        )
        return qa_result

    # 调用混合检索服务并把证据包写入工作流状态。
    async def _retrieve(self, state: QAState) -> dict:
        bundle = await self.retrieval.retrieve(
            state["question"],
            state["scope"],
            state["options"],
            trace_id=state["trace_id"],
        )
        return {"retrieval": bundle}

    # 根据证据是否充分选择继续生成或直接拒答。
    @staticmethod
    def _route_after_retrieval(state: QAState) -> Literal["generate", "abstain"]:
        return "generate" if state["retrieval"].sufficient else "abstain"

    # 使用最终证据生成候选答案。
    async def _generate(self, state: QAState) -> dict:
        answer = await self.generator.generate(
            state["question"], state["retrieval"].selected_evidence
        )
        return {"answer": answer, "refused": False}

    # 校验答案引用，并在首次失败时尝试修复一次。
    async def _validate(self, state: QAState) -> dict:
        evidence = state["retrieval"].selected_evidence
        validation = validate_citations(state["answer"], evidence)
        answer = state["answer"]
        if not validation.valid:
            answer = await self.generator.repair(state["question"], evidence, answer)
            validation = validate_citations(answer, evidence)
            validation.repaired = True
        if not validation.valid:
            raise CitationValidationError(
                f"Generated answer failed citation validation: {validation.errors}"
            )
        return {"answer": answer, "validation": validation}

    # 在证据不足时返回固定拒答内容和有效空校验结果。
    @staticmethod
    async def _abstain(state: QAState) -> dict:
        return {
            "answer": "当前知识库中没有足够证据回答这个问题。请补充相关平台文档或设备资料。",
            "refused": True,
            "validation": ValidationResult(valid=True),
        }
