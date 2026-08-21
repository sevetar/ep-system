from __future__ import annotations

from collections.abc import Sequence

import httpx
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from flowfix_agent.retrieval.models import Evidence, RetrievalCandidate


# 剥离模型输出中防御性的 markdown 代码围栏，只保留 JSON 文本。
def strip_code_fence(text: str) -> str:
    text = text.strip()
    lines = text.splitlines()
    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


# 将结构化证据格式化为模型提示词可读取的编号文本块。
def format_evidence(evidence: Sequence[Evidence]) -> str:
    blocks = []
    for item in evidence:
        location = (
            f"{item.title} / {item.section_path}" if item.section_path else item.title
        )
        blocks.append(
            f"[{item.citation_id}] 来源：{location}，版本：{item.source_version}\n"
            f"{item.content}"
        )
    return "\n\n".join(blocks)


# 通过 OpenAI 兼容接口生成文档和查询向量。
class OpenAICompatibleEmbeddings:
    # 初始化模型客户端并记录期望的向量维度。
    def __init__(
        self,
        client: httpx.AsyncClient,
        model: str,
        dimensions: int,
    ) -> None:
        self.client = client
        self.model = model
        self.dimensions = dimensions

    # 批量生成知识文档文本的向量表示。
    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return await self._embed(list(texts))

    # 生成单条检索查询的向量表示。
    async def embed_query(self, text: str) -> list[float]:
        vectors = await self._embed([text])
        return vectors[0]

    # 调用远程 Embedding 接口并校验返回数量与维度。
    async def _embed(self, texts: list[str]) -> list[list[float]]:
        response = await self.client.post(
            "embeddings",
            json={"model": self.model, "input": texts},
        )
        response.raise_for_status()
        payload = response.json()
        items = sorted(payload["data"], key=lambda item: item.get("index", 0))
        vectors = [item["embedding"] for item in items]
        if len(vectors) != len(texts):
            raise ValueError("Embedding provider returned a different number of vectors")
        if any(len(vector) != self.dimensions for vector in vectors):
            raise ValueError("Embedding provider returned an unexpected vector dimension")
        return vectors


# 通过 OpenAI 兼容接口对召回候选进行语义重排。
class OpenAICompatibleReranker:
    # 初始化重排模型使用的异步客户端和模型名称。
    def __init__(self, client: httpx.AsyncClient, model: str) -> None:
        self.client = client
        self.model = model

    # 按查询与候选内容的相关性返回候选下标和重排分数。
    async def rerank(
        self,
        query: str,
        candidates: Sequence[RetrievalCandidate],
    ) -> list[tuple[int, float]]:
        response = await self.client.post(
            "rerank",
            json={
                "model": self.model,
                "query": query,
                "documents": [candidate.content for candidate in candidates],
                "top_n": len(candidates),
            },
        )
        response.raise_for_status()
        results = response.json()["results"]
        return [
            (int(item["index"]), float(item["relevance_score"]))
            for item in results
        ]


# 使用 LangChain 组织受证据约束的答案生成与引用修复链。
class LangChainAnswerGenerator:
    # 创建聊天模型、回答提示词、修复提示词和解析链。
    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float,
    ) -> None:
        chat = ChatOpenAI(
            api_key=api_key,
            base_url=base_url,
            model=model,
            temperature=0,
            timeout=timeout_seconds,
            max_retries=1,
        )
        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "你是 FlowFix 设备运维知识助手。只能依据给定证据回答。"
                    "每个事实后使用 [数字] 引用对应证据；不得引用不存在的编号。"
                    "证据不足时明确说不知道，不得用模型常识补全。不要输出内部推理过程。",
                ),
                (
                    "human",
                    "问题：{question}\n\n证据：\n{evidence}\n\n"
                    "请给出简洁、准确、带引用的中文回答。",
                ),
            ]
        )
        repair_prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "修复回答的引用格式。只能保留给定证据支持的内容，"
                    "并使用 [数字] 引用；不要添加新事实。",
                ),
                (
                    "human",
                    "问题：{question}\n\n证据：\n{evidence}\n\n原回答：\n{draft}\n\n"
                    "输出修复后的最终回答。",
                ),
            ]
        )
        parser = StrOutputParser()
        self._chain = prompt | chat | parser
        self._repair_chain = repair_prompt | chat | parser
        self.model = model

    # 根据问题和已筛选证据生成带引用的中文答案。
    async def generate(self, question: str, evidence: Sequence[Evidence]) -> str:
        return await self._chain.ainvoke(
            {"question": question, "evidence": self._format_evidence(evidence)}
        )

    # 在引用校验失败时修复答案内容和引用编号。
    async def repair(
        self,
        question: str,
        evidence: Sequence[Evidence],
        draft: str,
    ) -> str:
        return await self._repair_chain.ainvoke(
            {
                "question": question,
                "evidence": self._format_evidence(evidence),
                "draft": draft,
            }
        )

    # 将结构化证据格式化为模型提示词可读取的编号文本块。
    @staticmethod
    def _format_evidence(evidence: Sequence[Evidence]) -> str:
        return format_evidence(evidence)
