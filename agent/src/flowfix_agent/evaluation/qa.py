from __future__ import annotations

import math
import platform
import statistics
import time
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from flowfix_agent.bootstrap.container import AppContainer
from flowfix_agent.core.models import RequestScope
from flowfix_agent.evaluation.common import load_jsonl_dataset, write_json_report
from flowfix_agent.retrieval.models import RetrievalMode, RetrievalOptions

# 证据筛选器可能给出的四个过滤原因，用于保证 filter_stats 键齐全且顺序稳定。
FILTER_REASON_KEYS = (
    "top_k_limit",
    "duplicate_content",
    "below_relevance_threshold",
    "evidence_budget",
)


# 定义固定评测集中一条问题及其相关来源和预期行为。
class EvaluationCase(BaseModel):
    case_id: str
    query: str
    relevant_sources: list[str] = Field(default_factory=list)
    answerable: bool = True
    expected_terms: list[str] = Field(default_factory=list)
    slice: Literal[
        "single_document",
        "multi_document",
        "unanswerable",
        "prompt_injection",
        "cross_tenant",
        "general",
    ] = "general"
    scope: RequestScope = Field(default_factory=RequestScope)

    @model_validator(mode="after")
    def validate_labels(self) -> EvaluationCase:
        if self.answerable and not self.relevant_sources:
            raise ValueError("answerable cases require relevant_sources")
        if not self.answerable and self.relevant_sources:
            raise ValueError("unanswerable cases cannot declare relevant_sources")
        return self


# 使用通用 JSONL 加载器读取 QA 与检索评测数据集。
def load_dataset(path: Path) -> list[EvaluationCase]:
    return load_jsonl_dataset(path, EvaluationCase, "QA")


# 在相同数据集上执行检索消融和可选的端到端问答评测。
async def run_l2_evaluation(
    container: AppContainer,
    dataset_path: Path,
    include_qa: bool = True,
) -> dict:
    cases = load_dataset(dataset_path)
    configurations = [
        ("bm25", RetrievalOptions(mode=RetrievalMode.BM25, rerank=False)),
        ("dense", RetrievalOptions(mode=RetrievalMode.DENSE, rerank=False)),
        ("hybrid", RetrievalOptions(mode=RetrievalMode.HYBRID, rerank=False)),
        ("hybrid_rerank", RetrievalOptions(mode=RetrievalMode.HYBRID, rerank=True)),
    ]
    results: dict[str, dict] = {}
    for name, options in configurations:
        answerable_metrics = []
        unanswerable_no_evidence = []
        latencies = []
        filter_rows = []
        slice_rows: dict[str, list[dict]] = defaultdict(list)
        for case in cases:
            bundle = await container.retrieval.retrieve(case.query, case.scope, options)
            latencies.append(bundle.latency_ms)
            filter_rows.append(
                {
                    "filter_reasons": [item.filter_reason for item in bundle.candidates],
                    "budget_used": bundle.budget_used,
                }
            )
            if case.answerable:
                candidate_sources = _unique(
                    [item.source_id for item in bundle.candidates]
                )
                selected_sources = [item.source_id for item in bundle.selected_evidence]
                row = {
                    "hit": float(
                        any(item in case.relevant_sources for item in candidate_sources)
                    ),
                    "mrr": _reciprocal_rank(candidate_sources, case.relevant_sources),
                    "ndcg": _ndcg(candidate_sources, case.relevant_sources),
                    # 该指标=最终被选证据里相关源占比（Context Recall），不是 Prompt Injection 检测。
                    "context_recall": _source_recall(
                        selected_sources, case.relevant_sources
                    ),
                    "context_precision": _source_precision(
                        selected_sources, case.relevant_sources
                    ),
                }
                answerable_metrics.append(row)
                slice_rows[case.slice].append(row)
            else:
                no_evidence = float(not bundle.selected_evidence)
                unanswerable_no_evidence.append(no_evidence)
                slice_rows[case.slice].append({"no_evidence": no_evidence})
        results[name] = {
            "cases": len(cases),
            "answerable_cases": len(answerable_metrics),
            "unanswerable_cases": len(unanswerable_no_evidence),
            "hit_rate": _mean(answerable_metrics, "hit"),
            "mrr": _mean(answerable_metrics, "mrr"),
            "ndcg": _mean(answerable_metrics, "ndcg"),
            "context_recall": _mean(answerable_metrics, "context_recall"),
            "context_precision": _mean(answerable_metrics, "context_precision"),
            "unanswerable_no_evidence_rate": round(
                statistics.fmean(unanswerable_no_evidence), 4
            )
            if unanswerable_no_evidence
            else None,
            "latency_p50_ms": round(statistics.median(latencies), 2),
            "latency_p95_ms": round(_percentile(latencies, 0.95), 2),
            "filter_stats": _summarize_filter_stats(filter_rows),
            "slices": {
                slice_name: _summarize_retrieval_slice(rows)
                for slice_name, rows in sorted(slice_rows.items())
            },
        }

    qa_metrics = None
    if include_qa:
        citation_valid = []
        behavior_correct = []
        term_recall = []
        latencies = []
        qa_slice_rows: dict[str, list[dict]] = defaultdict(list)
        for case in cases:
            started = time.perf_counter()
            result = await container.qa.run(case.query, scope=case.scope)
            latencies.append((time.perf_counter() - started) * 1000)
            citation_score = float(result.validation.valid)
            behavior_score = float(result.refused != case.answerable)
            citation_valid.append(citation_score)
            behavior_correct.append(behavior_score)
            row = {
                "citation_valid": citation_score,
                "behavior_correct": behavior_score,
            }
            if case.expected_terms and not result.refused:
                matched = sum(
                    term.lower() in result.answer.lower() for term in case.expected_terms
                )
                recall = matched / len(case.expected_terms)
                term_recall.append(recall)
                row["term_recall"] = recall
            qa_slice_rows[case.slice].append(row)
        qa_metrics = {
            "cases": len(cases),
            "citation_valid_rate": round(statistics.fmean(citation_valid), 4),
            "answer_refusal_accuracy": round(statistics.fmean(behavior_correct), 4),
            "expected_term_recall": round(statistics.fmean(term_recall), 4)
            if term_recall
            else None,
            "latency_p50_ms": round(statistics.median(latencies), 2),
            "latency_p95_ms": round(_percentile(latencies, 0.95), 2),
            "slices": {
                slice_name: _summarize_qa_slice(rows)
                for slice_name, rows in sorted(qa_slice_rows.items())
            },
        }

    active_records = await container.catalog.list_active()
    settings = container.settings
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "dataset": str(dataset_path),
        "runtime": {
            "python": platform.python_version(),
            "elasticsearch_index": settings.elasticsearch_index,
        },
        "knowledge": {
            "sources": len(active_records),
            "chunks": sum(item.indexed_chunks for item in active_records),
            "active_versions": {
                item.source_id: item.active_version for item in active_records
            },
        },
        "models": {
            "chat": settings.chat_model,
            "embedding": settings.embedding_model,
            "embedding_dimensions": settings.embedding_dimensions,
            "reranker": settings.rerank_model,
        },
        "retrieval_parameters": {
            "bm25_top_k": settings.bm25_top_k,
            "vector_top_k": settings.vector_top_k,
            "final_top_k": settings.final_top_k,
            "rrf_k": settings.rrf_k,
            "vector_min_score": settings.vector_min_score,
            "rerank_min_score": settings.rerank_min_score,
            "evidence_token_budget": settings.evidence_token_budget,
        },
        "retrieval": results,
        "qa": qa_metrics,
    }


# 使用通用报告写入器保存 QA 与检索评测结果。
def write_report(report: dict, path: Path) -> None:
    write_json_report(report, path)


# 计算第一个相关来源对应的倒数排名分数。
def _reciprocal_rank(retrieved: list[str], relevant: list[str]) -> float:
    for rank, source in enumerate(retrieved, start=1):
        if source in relevant:
            return 1.0 / rank
    return 0.0


# 计算已召回相关来源占全部标注相关来源的比例。
def _source_recall(retrieved: list[str], relevant: list[str]) -> float:
    if not relevant:
        return float(not retrieved)
    return len(set(retrieved) & set(relevant)) / len(set(relevant))


# 计算最终被选证据中相关来源占全部被选来源的比例；无被选来源时返回 0.0。
def _source_precision(retrieved: list[str], relevant: list[str]) -> float:
    if not retrieved:
        return 0.0
    return len(set(retrieved) & set(relevant)) / len(set(retrieved))


# 计算二元相关性标注下的归一化折损累计增益。
def _ndcg(retrieved: list[str], relevant: list[str]) -> float:
    if not relevant:
        return float(not retrieved)
    dcg = sum(
        1.0 / math.log2(rank + 1)
        for rank, source in enumerate(retrieved, start=1)
        if source in relevant
    )
    ideal_hits = min(len(set(relevant)), len(retrieved))
    ideal = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))
    return dcg / ideal if ideal else 0.0


# 汇总指定指标字段的算术平均值并保留四位小数。
def _mean(metrics: list[dict], key: str) -> float:
    return round(statistics.fmean(item[key] for item in metrics), 4)


# 汇总各检索配置的候选过滤原因分布与证据预算消耗统计。
# rows 中每个元素为 {"filter_reasons": list[str | None], "budget_used": int}，
# 其中 filter_reason 为 None 表示候选被选中。
def _summarize_filter_stats(rows: list[dict]) -> dict:
    reason_counts: Counter[str | None] = Counter()
    budget_used_values: list[int] = []
    for row in rows:
        reason_counts.update(row["filter_reasons"])
        budget_used_values.append(row["budget_used"])
    return {
        "total_candidates": sum(reason_counts.values()),
        "selected": reason_counts.get(None, 0),
        **{key: reason_counts.get(key, 0) for key in FILTER_REASON_KEYS},
        "budget_used_avg": round(statistics.fmean(budget_used_values), 2),
        "budget_used_p50": round(statistics.median(budget_used_values), 2),
        "budget_used_p95": round(_percentile(budget_used_values, 0.95), 2),
    }


def _summarize_retrieval_slice(rows: list[dict]) -> dict:
    summary: dict[str, float | int] = {"cases": len(rows)}
    for key in (
        "hit",
        "mrr",
        "ndcg",
        "context_recall",
        "context_precision",
        "no_evidence",
    ):
        values = [row[key] for row in rows if key in row]
        if values:
            summary[key] = round(statistics.fmean(values), 4)
    return summary


def _summarize_qa_slice(rows: list[dict]) -> dict:
    summary: dict[str, float | int] = {"cases": len(rows)}
    for key in ("citation_valid", "behavior_correct", "term_recall"):
        values = [row[key] for row in rows if key in row]
        if values:
            summary[key] = round(statistics.fmean(values), 4)
    return summary


# 在保持原有顺序的前提下去除重复字符串。
def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


# 通过线性插值计算给定浮点序列的目标百分位数。
def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)
