from __future__ import annotations

import asyncio
import time
import uuid

from flowfix_agent.core.errors import DependencyUnavailableError
from flowfix_agent.core.models import RequestScope
from flowfix_agent.knowledge.models import CatalogRecord
from flowfix_agent.knowledge.ports import EmbeddingPort, KnowledgeCatalogPort, TracePort
from flowfix_agent.retrieval.fusion import reciprocal_rank_fusion
from flowfix_agent.retrieval.models import (
    EvidenceBundle,
    RetrievalCandidate,
    RetrievalMode,
    RetrievalOptions,
)
from flowfix_agent.retrieval.ports import RerankerPort, SearchPort
from flowfix_agent.retrieval.selector import EvidenceSelector


# 编排 BM25、向量召回、RRF、重排和最终证据筛选流程。
class HybridRetrievalService:
    # 注入检索链所需端口、筛选器和各阶段参数。
    def __init__(
        self,
        # 搜索端口：提供 BM25 与向量检索两种召回能力
        search: SearchPort,
        # 知识目录端口：列出当前活跃的知识版本
        catalog: KnowledgeCatalogPort,
        # 嵌入端口：把查询文本编码为向量
        embedding: EmbeddingPort,
        # 证据筛选器：从候选中按预算选出最终证据
        selector: EvidenceSelector,
        # 追踪端口：上报检索血缘与指标
        trace: TracePort,
        # 重排端口：可选，用于对融合结果二次排序
        reranker: RerankerPort | None,
        # BM25 召回数量上限
        bm25_top_k: int,
        # 向量召回数量上限
        vector_top_k: int,
        # RRF 融合常数 k
        rrf_k: int,
        # 是否启用重排（可被请求级选项覆盖）
        rerank_enabled: bool,
    ) -> None:
        # 保存搜索端口
        self.search = search
        # 保存知识目录端口
        self.catalog = catalog
        # 保存嵌入端口
        self.embedding = embedding
        # 保存证据筛选器
        self.selector = selector
        # 保存追踪端口
        self.trace = trace
        # 保存重排端口（可能为 None）
        self.reranker = reranker
        # 保存 BM25 召回数量上限
        self.bm25_top_k = bm25_top_k
        # 保存向量召回数量上限
        self.vector_top_k = vector_top_k
        # 保存 RRF 融合常数
        self.rrf_k = rrf_k
        # 保存重排开关
        self.rerank_enabled = rerank_enabled

    # 执行一次可降级、可追踪的完整检索请求。
    async def retrieve(
        # 实例自身（绑定方法）
        self,
        # 用户查询文本
        query: str,
        # 请求访问范围（租户/可见性/设备过滤条件）
        scope: RequestScope,
        # 检索选项：模式、top_k、重排覆盖等，为空时用默认值
        options: RetrievalOptions | None = None,
        # 链路追踪 ID，为空时自动生成
        trace_id: str | None = None,
    ) -> EvidenceBundle:
        # 选项为空时回退到默认检索选项
        options = options or RetrievalOptions()
        # 追踪 ID 为空时生成新的十六进制串
        trace_id = trace_id or uuid.uuid4().hex
        # 记录检索开始时间，用于计算延迟
        started = time.perf_counter()
        # 记录降级事件（某路召回失败、重排失败等），供上层判断证据可信度
        fallbacks: list[str] = []
        # 列出当前活跃的知识版本记录
        records = await self.catalog.list_active()
        # 过滤掉当前请求访问范围之外的知识记录
        records = [record for record in records if self._record_allowed(record, scope)]
        # 提取可检索知识的 knowledge_key 列表
        knowledge_keys = [record.knowledge_key for record in records]
        # 若无任何可检索知识版本
        if not knowledge_keys:
            # 构造并返回空证据包（sufficient=False），并记录降级原因
            return await self._empty_bundle(
                query, scope, options, trace_id, started, ["empty_catalog"]
            )
        # 按模式执行单路或双路召回并融合候选
        candidates = await self._recall(query, scope, options.mode, knowledge_keys, fallbacks)
        # 重排开关：请求级选项优先，其次用服务默认值
        rerank_requested = options.rerank if options.rerank is not None else self.rerank_enabled
        # 需要重排、存在重排器且有候选时才进入重排
        if rerank_requested and self.reranker and candidates:
            # 尝试执行重排
            try:
                # 应用重排结果覆盖候选得分与排序
                candidates = await self._apply_rerank(query, candidates)
            # 重排失败不应阻断整个检索
            except Exception as exc:
                # 记录重排降级事件
                fallbacks.append(f"reranker_failed:{type(exc).__name__}")
        # 用筛选器从候选中按预算选出最终证据，返回已用预算
        selected, budget_used = self.selector.select(candidates, options.top_k)
        # 计算检索总延迟（毫秒）
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        # 组装最终证据包
        bundle = EvidenceBundle(
            # 检索追踪 ID
            trace_id=trace_id,
            # 原始查询文本
            original_query=query,
            # 实际用于检索的查询文本（当前与原始一致，为改写预留）
            retrieval_query=query,
            # 本次检索模式（BM25/DENSE/HYBRID）
            mode=options.mode,
            # 本次检索的访问范围
            scope=scope,
            # 全部候选（融合/重排后的完整列表）
            candidates=candidates,
            # 最终选中的证据
            selected_evidence=selected,
            # 已消耗的证据预算
            budget_used=budget_used,
            # 有选中证据即视为证据充分
            sufficient=bool(selected),
            # 本次检索发生的降级事件列表
            fallbacks=fallbacks,
            # 本次检索延迟
            latency_ms=latency_ms,
        )
        # 上报检索完成的血缘与指标
        await self.trace.emit(
            # 事件名：检索完成
            "retrieval.completed",
            # 关联的追踪 ID
            trace_id,
            {
                # 查询文本
                "query": query,
                # 检索模式
                "mode": options.mode,
                # 访问范围（JSON 序列化）
                "scope": scope.model_dump(mode="json"),
                # 逐候选项的得分与选中状态明细
                "candidates": [
                    # 逐候选项展开字段
                    {
                        # 候选分块 ID
                        "chunk_id": item.chunk_id,
                        # 融合后的最终名次
                        "rank": item.rank,
                        # BM25 得分
                        "bm25_score": item.bm25_score,
                        # 向量相似度得分
                        "vector_score": item.vector_score,
                        # RRF 融合得分
                        "rrf_score": item.rrf_score,
                        # 重排得分（未重排则为 None）
                        "rerank_score": item.rerank_score,
                        # 是否被选中为证据
                        "selected": item.selected,
                        # 未选中的过滤原因
                        "filter_reason": item.filter_reason,
                    }
                    # 遍历全部候选
                    for item in candidates
                ],
                # 最终选中证据的 chunk_id 列表
                "selected_ids": [item.chunk_id for item in selected],
                # 降级事件列表
                "fallbacks": fallbacks,
                # 检索延迟
                "latency_ms": latency_ms,
            },
        )
        # 返回组装好的证据包
        return bundle

    # 根据模式执行单路召回或并行双路召回与 RRF 融合。
    async def _recall(
        # 实例自身（绑定方法）
        self,
        # 查询文本
        query: str,
        # 访问范围
        scope: RequestScope,
        # 检索模式
        mode: RetrievalMode,
        # 可检索知识的 knowledge_key 列表
        knowledge_keys: list[str],
        # 降级事件收集列表
        fallbacks: list[str],
    ) -> list[RetrievalCandidate]:
        # 纯 BM25 模式：直接执行单路召回
        if mode == RetrievalMode.BM25:
            # 返回 BM25 召回结果
            return await self._bm25(query, scope, knowledge_keys)
        # 纯 DENSE 模式：直接执行单路语义召回
        if mode == RetrievalMode.DENSE:
            # 返回向量召回结果
            return await self._dense(query, scope, knowledge_keys)
        # 混合模式：并行执行 BM25 与向量召回，单路失败不阻断另一路
        bm25_result, dense_result = await asyncio.gather(
            # 第一路：BM25 召回
            self._bm25(query, scope, knowledge_keys),
            # 第二路：向量召回
            self._dense(query, scope, knowledge_keys),
            # 失败以异常对象返回而非直接抛出，便于降级处理
            return_exceptions=True,
        )
        # 收集成功的召回结果集
        result_sets: list[list[RetrievalCandidate]] = []
        # BM25 路以异常对象返回说明该路失败
        if isinstance(bm25_result, BaseException):
            # 记录 BM25 降级事件
            fallbacks.append(f"bm25_failed:{type(bm25_result).__name__}")
        # BM25 路成功
        else:
            # 收入成功结果集
            result_sets.append(bm25_result)
        # DENSE 路以异常对象返回说明该路失败
        if isinstance(dense_result, BaseException):
            # 记录向量召回降级事件
            fallbacks.append(f"dense_failed:{type(dense_result).__name__}")
        # DENSE 路成功
        else:
            # 收入成功结果集
            result_sets.append(dense_result)
        # 两路全部失败：抛依赖不可用错误，交由上层决定
        if not result_sets:
            # 抛出混合检索双路全失败错误
            raise DependencyUnavailableError("Both BM25 and Dense retrieval failed")
        # 对成功的结果集执行 RRF 融合并返回融合候选
        return reciprocal_rank_fusion(result_sets, self.rrf_k)

    # 调用搜索端口执行带访问范围过滤的 BM25 召回。
    async def _bm25(
        # 实例自身（绑定方法）
        self,
        # 查询文本
        query: str,
        # 访问范围（携带过滤条件）
        scope: RequestScope,
        # 可检索知识的 knowledge_key 列表
        knowledge_keys: list[str],
    ) -> list[RetrievalCandidate]:
        # 委托搜索端口执行关键词召回，携带知识范围与访问过滤条件
        return await self.search.bm25_search(
            # 查询文本
            query,
            # 限定可检索的知识键
            knowledge_keys,
            # 召回数量上限
            self.bm25_top_k,
            # 租户过滤
            scope.tenant_id,
            # 可见性过滤
            scope.visibility,
            # 设备品类过滤
            scope.device_category,
            # 设备型号过滤
            scope.device_model,
        )

    # 生成查询向量并执行带访问范围过滤的语义召回。
    async def _dense(
        # 实例自身（绑定方法）
        self,
        # 查询文本
        query: str,
        # 访问范围（携带过滤条件）
        scope: RequestScope,
        # 可检索知识的 knowledge_key 列表
        knowledge_keys: list[str],
    ) -> list[RetrievalCandidate]:
        # 用嵌入端口把查询编码成向量
        vector = await self.embedding.embed_query(query)
        # 委托搜索端口执行向量检索，携带访问过滤条件
        return await self.search.vector_search(
            # 查询向量
            vector,
            # 限定可检索的知识键
            knowledge_keys,
            # 召回数量上限
            self.vector_top_k,
            # 租户过滤
            scope.tenant_id,
            # 可见性过滤
            scope.visibility,
            # 设备品类过滤
            scope.device_category,
            # 设备型号过滤
            scope.device_model,
        )

    # 应用远程重排结果并保留服务未返回的原候选。
    async def _apply_rerank(
        # 实例自身（绑定方法）
        self,
        # 查询文本
        query: str,
        # 待重排的候选列表
        candidates: list[RetrievalCandidate],
    ) -> list[RetrievalCandidate]:
        # 防御：重排器必须存在才能进入本方法
        assert self.reranker is not None
        # 调用重排器，得到 (索引, 得分) 顺序列表
        ranking = await self.reranker.rerank(query, candidates)
        # 保存被重排器覆盖得分的候选
        ranked: list[RetrievalCandidate] = []
        # 记录已处理过的候选索引，防止重复
        seen: set[int] = set()
        # 遍历重排结果
        for index, score in ranking:
            # 索引越界或已处理过则跳过
            if index < 0 or index >= len(candidates) or index in seen:
                continue
            # 标记该索引已处理
            seen.add(index)
            # 深拷贝候选，避免污染原始对象
            candidate = candidates[index].model_copy(deep=True)
            # 写入重排得分
            candidate.rerank_score = score
            # 用重排得分覆盖最终得分
            candidate.score = score
            # 把 "reranker" 加入检索来源标记（去重）
            candidate.retrieval_sources = list(
                dict.fromkeys(candidate.retrieval_sources + ["reranker"])
            )
            # 收集重排后的候选
            ranked.append(candidate)
        # 保留重排器未返回的候选，避免丢结果
        for index, candidate in enumerate(candidates):
            # 未出现在重排结果中的候选
            if index not in seen:
                # 深拷贝并追加，保持原得分
                ranked.append(candidate.model_copy(deep=True))
        # 按最终顺序重写名次（从 1 开始）
        for rank, candidate in enumerate(ranked, start=1):
            # 覆盖名次字段
            candidate.rank = rank
        # 返回重排后的候选列表
        return ranked

    # 在没有可访问知识版本时构造并记录空证据包。
    async def _empty_bundle(
        # 实例自身（绑定方法）
        self,
        # 查询文本
        query: str,
        # 访问范围
        scope: RequestScope,
        # 检索选项
        options: RetrievalOptions,
        # 追踪 ID
        trace_id: str,
        # 起始计时时刻
        started: float,
        # 降级原因列表
        fallbacks: list[str],
    ) -> EvidenceBundle:
        # 构造空证据包：无候选、无证据、证据不足
        bundle = EvidenceBundle(
            # 追踪 ID
            trace_id=trace_id,
            # 原始查询
            original_query=query,
            # 检索查询
            retrieval_query=query,
            # 检索模式
            mode=options.mode,
            # 访问范围
            scope=scope,
            # 空候选列表
            candidates=[],
            # 空证据列表
            selected_evidence=[],
            # 零预算消耗
            budget_used=0,
            # 证据不足
            sufficient=False,
            # 降级原因
            fallbacks=fallbacks,
            # 计算延迟
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        # 上报检索完成事件（空结果）
        await self.trace.emit(
            # 事件名：检索完成
            "retrieval.completed",
            # 追踪 ID
            trace_id,
            {
                # 查询文本
                "query": query,
                # 检索模式
                "mode": options.mode,
                # 访问范围（JSON）
                "scope": scope.model_dump(mode="json"),
                # 空候选
                "candidates": [],
                # 空选中
                "selected_ids": [],
                # 降级原因
                "fallbacks": fallbacks,
                # 延迟
                "latency_ms": bundle.latency_ms,
            },
        )
        # 返回空证据包
        return bundle

    # 判断目录记录是否满足请求指定的来源和租户可见范围。
    @staticmethod
    def _record_allowed(record: CatalogRecord, scope: RequestScope) -> bool:
        # 取出记录来源 ID
        source_id = record.source_id
        # 取出记录来源类型（字符串化）
        source_type = str(record.source_type)
        # 取出记录可见性
        visibility = record.visibility
        # 取出记录所属租户
        tenant_id = record.tenant_id
        # 请求限定了来源 ID 且当前记录不在其中
        if scope.source_ids and source_id not in scope.source_ids:
            # 不允许访问
            return False
        # 请求限定了来源类型且当前记录不在其中
        if scope.source_types and source_type not in scope.source_types:
            # 不允许访问
            return False
        # 公共记录对任何请求可见
        if visibility == "public":
            # 允许访问
            return True
        # 非公共记录：仅当请求为租户级且租户一致时可见
        return scope.visibility == "tenant" and tenant_id == scope.tenant_id
