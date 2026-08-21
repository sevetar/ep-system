# 启用对来自 __future__ 的注解（如 list[int]）的延迟求值，与 Python 3.12 兼容
from __future__ import annotations

# 导入只读的序列抽象类型，用于标注结果集输入
from collections.abc import Sequence

# 导入检索候选模型，作为融合处理的元素类型
from flowfix_agent.retrieval.models import RetrievalCandidate


# 使用倒数排名融合多个结果集，避免直接比较不同量纲的原始分数。
def reciprocal_rank_fusion(
    # 多个召回结果集（BM25 与向量召回的输出）
    result_sets: Sequence[Sequence[RetrievalCandidate]],
    # RRF 融合常数 k，平滑高分排名的影响，默认 60
    rank_constant: int = 60,
) -> list[RetrievalCandidate]:
    # 按分块 ID 存放融合后的唯一候选（保留首次出现的深拷贝）
    by_id: dict[str, RetrievalCandidate] = {}
    # 按分块 ID 累加 RRF 得分
    scores: dict[str, float] = {}
    # 遍历每一个召回结果集
    for result_set in result_sets:
        # 枚举该结果集中的候选，排名从 1 开始
        for rank, candidate in enumerate(result_set, start=1):
            # 从字典中取该分块已存在的融合候选
            existing = by_id.get(candidate.chunk_id)
            # 该分块第一次出现
            if existing is None:
                # 深拷贝候选，避免污染原结果集
                existing = candidate.model_copy(deep=True)
                # 放入融合候选字典
                by_id[candidate.chunk_id] = existing
                # 初始化该分块的 RRF 得分
                scores[candidate.chunk_id] = 0.0
            # 该分块已出现过（多路召回命中同一分块）
            else:
                # 合并检索来源标记，用字典去重后再转回列表
                existing.retrieval_sources = list(
                    dict.fromkeys(existing.retrieval_sources + candidate.retrieval_sources)
                )
                # 当前候选携带 BM25 得分时更新融合候选的 BM25 得分
                if candidate.bm25_score is not None:
                    existing.bm25_score = candidate.bm25_score
                # 当前候选携带向量得分时更新融合候选的向量得分
                if candidate.vector_score is not None:
                    existing.vector_score = candidate.vector_score
            # 累加该分块的 RRF 得分：1 / (k + rank)，排名越靠前贡献越大
            scores[candidate.chunk_id] += 1.0 / (rank_constant + rank)

    # 取出全部融合候选（每个分块唯一）
    fused = list(by_id.values())
    # 遍历融合候选，回填 RRF 得分
    for candidate in fused:
        # 写入该分块的累计 RRF 得分
        candidate.rrf_score = scores[candidate.chunk_id]
        # 用 RRF 得分作为最终的排序得分
        candidate.score = candidate.rrf_score
    # 按得分降序、同分按分块 ID 升序排序
    fused.sort(key=lambda item: (-item.score, item.chunk_id))
    # 重写最终名次，从 1 开始
    for rank, candidate in enumerate(fused, start=1):
        # 覆盖名次字段
        candidate.rank = rank
    # 返回融合并排序后的候选列表
    return fused
