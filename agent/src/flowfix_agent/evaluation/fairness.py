from __future__ import annotations

import platform
import tempfile
from collections import Counter
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from flowfix_agent.core.models import RequestScope
from flowfix_agent.evaluation.common import (
    load_jsonl_dataset,
    write_json_report,
)
from flowfix_agent.evaluation.golden import (
    _assemble_scenario,
    _build_table,
    _refusal_present,
    _unacknowledged_risk,
)
from flowfix_agent.evaluation.impact_safety import (
    CannedEvidenceItem,
    CannedRetrieval,
)
from flowfix_agent.investigation.loop import InvestigationLoop
from flowfix_agent.investigation.models import (
    AgentDecision,
    InvestigationRequest,
    StopReason,
)
from flowfix_agent.memory.task_artifact import SQLiteTaskArtifactStore
from flowfix_agent.planning.completion import CompletionGate
from flowfix_agent.planning.controller import PlanController
from flowfix_agent.planning.models import IncidentContext
from flowfix_agent.planning.registry import WorkerRegistry
from flowfix_agent.planning.replanning import RuleBasedReplanDetector, RuleBasedReplanner
from flowfix_agent.planning.runtime import PlanningRuntime
from flowfix_agent.planning.validation import PlanValidator
from flowfix_agent.retrieval.models import RetrievalOptions
from flowfix_agent.tools import ToolGateway, ToolRegistry, ToolResolver
from flowfix_agent.tools.models import ToolCall
from flowfix_agent.tools.providers import (
    RetrievalCapabilityClient,
    RetrievalToolProvider,
    knowledge_search_spec,
)
from flowfix_agent.tools.providers.retrieval import KNOWLEDGE_SEARCH

# 单次检索的固定令牌开销假设，用于跨两种执行方式的成本对比。
_TOKENS_PER_CALL = 50


# 注入的工具故障类型：无故障、单次瞬时故障、持续故障。
class FaultKind(StrEnum):
    NONE = "none"
    TRANSIENT = "transient"
    PERSISTENT = "persistent"


# 表示一条公平评测用例：同一目标/证据/预算/故障分别跑单 Agent 与多 Agent 链路。
class FairnessCase(BaseModel):
    case_id: str
    goal: str
    scenario: Literal["basic", "replan-new-evidence", "replan-resource"]
    success_criteria: list[str] = Field(default_factory=list)
    max_queries: int = Field(default=3, ge=1, le=10)
    fault: FaultKind = FaultKind.NONE
    # 查询命中该关键词时触发故障；为空则不注入。
    fault_keyword: str | None = None
    evidence: dict[str, list[CannedEvidenceItem]] = Field(default_factory=dict)


# 包装固定证据检索：记录每次查询与返回证据规模，并按配置注入工具故障。
class RecordingFaultRetrieval:
    """两种 Agent 共享同一检索底座，故障语义一致以保证评测公平。"""

    # 绑定底层检索与故障配置。
    def __init__(
        self,
        retrieval,
        fault: FaultKind = FaultKind.NONE,
        fault_keyword: str | None = None,
    ) -> None:
        self.retrieval = retrieval
        self.fault = fault
        self.fault_keyword = fault_keyword
        self.queries: list[str] = []
        self.evidence_tokens = 0
        self.calls = 0
        self.failures = 0

    # 记录查询后按故障类型注入失败，再委托底层检索并累计证据令牌。
    async def retrieve(self, query, scope, options, trace_id=None):
        self.calls += 1
        self.queries.append(query)
        if self.fault_keyword and self.fault_keyword in query:
            if self.fault == FaultKind.PERSISTENT:
                self.failures += 1
                raise ConnectionError("injected persistent retrieval fault")
            if self.fault == FaultKind.TRANSIENT and self.calls == 1:
                self.failures += 1
                raise ConnectionError("injected transient retrieval fault")
        bundle = await self.retrieval.retrieve(query, scope, options, trace_id=trace_id)
        self.evidence_tokens += sum(
            len(item.content) for item in bundle.selected_evidence
        )
        return bundle


# 确定性单 Agent 决策器：按目标与成功标准依次检索，命中证据即形成结论。
class DeterministicSingleAgent:
    """作为多 Agent 链路的公平对照：不做规划与重规划，单循环消耗同等检索预算。"""

    # 注入推导好的查询序列与固定上下文。
    def __init__(self, queries, scope, options, trace_id) -> None:
        self.queries = list(queries)
        self.scope = scope
        self.options = options
        self.trace_id = trace_id
        self.index = 0
        self.calls = 0

    # 单步决策：命中证据即结束；否则发起下一次检索或宣告证据不足。
    async def decide(self, request, specs, observations):
        if observations and observations[-1].success and (
            observations[-1].payload or {}
        ).get("selected_evidence"):
            return AgentDecision(
                conclusion="已获得支撑证据，形成调查结论。",
                stop_reason=StopReason.COMPLETED,
            )
        if self.index >= len(self.queries):
            return AgentDecision(stop_reason=StopReason.INSUFFICIENT_EVIDENCE)
        query = self.queries[self.index]
        self.index += 1
        self.calls += 1
        return AgentDecision(
            tool_call=ToolCall(
                call_id=f"single-agent-{self.calls}",
                capability=KNOWLEDGE_SEARCH,
                arguments={
                    "query": query,
                    "scope": self.scope.model_dump(mode="json"),
                    "options": self.options.model_dump(mode="json"),
                    "trace_id": f"{self.trace_id}:single:{self.calls}",
                },
            )
        )


# 使用通用 JSONL 加载器读取公平评测数据集。
def load_fairness_dataset(path: Path) -> list[FairnessCase]:
    return load_jsonl_dataset(path, FairnessCase, "fairness")


# 在固定数据集上同时运行单 Agent 与多 Agent 链路并汇总公平门禁指标。
async def run_fairness_evaluation(dataset_path: Path) -> dict:
    """同一工具/证据/预算/故障下对比两种执行方式，只读不访问真实模型或 ES。"""
    cases = load_fairness_dataset(dataset_path)
    rows: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="flowfix-fair-eval-") as temp_dir:
        for case in cases:
            rows.append(await _run_case(case, Path(temp_dir)))
    multi_success = sum(row["multi"]["success"] for row in rows)
    single_success = sum(row["single"]["success"] for row in rows)
    safety_violations = sum(row["safety_violations"] for row in rows)
    transient_rows = [row for row in rows if row["fault"] == "transient"]
    recovered = sum(row["multi"]["success"] for row in transient_rows)
    fault_recovery_rate = (
        round(recovered / len(transient_rows), 4) if transient_rows else 1.0
    )
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "milestone": "D19",
        "dataset": str(dataset_path),
        "runtime": {"python": platform.python_version(), "external_services_used": []},
        "metrics": {
            "total": len(rows),
            "multi_agent_success": multi_success,
            "single_agent_success": single_success,
            "success_parity": multi_success == single_success,
            "safety_violations": safety_violations,
            "fault_recovery_rate": fault_recovery_rate,
            "p95_queries_multi": _p95([row["multi"]["query_count"] for row in rows]),
            "p95_queries_single": _p95([row["single"]["query_count"] for row in rows]),
            "total_queries_multi": sum(row["multi"]["query_count"] for row in rows),
            "total_queries_single": sum(row["single"]["query_count"] for row in rows),
            "duplicate_queries_multi": sum(
                row["multi"]["duplicate_queries"] for row in rows
            ),
            "duplicate_queries_single": sum(
                row["single"]["duplicate_queries"] for row in rows
            ),
            "token_estimate_multi": sum(
                row["multi"]["token_estimate"] for row in rows
            ),
            "token_estimate_single": sum(
                row["single"]["token_estimate"] for row in rows
            ),
            "failure_buckets": dict(Counter(row["failure_bucket"] for row in rows)),
        },
        "gate": {
            "passed": bool(
                safety_violations == 0
                and fault_recovery_rate == 1.0
                and multi_success == single_success
            ),
            "criteria": {
                "safety_violations": 0,
                "fault_recovery_rate": 1.0,
                "success_parity": True,
            },
        },
        "cases": rows,
    }


# 运行单个公平用例：分别装配单 Agent 循环与多 Agent 调查链。
async def _run_case(case: FairnessCase, temp_dir: Path) -> dict:
    table = _build_table(case.evidence)
    scope = RequestScope(tenant_id="tenant-eval", visibility="tenant")
    options = RetrievalOptions()
    trace_id = f"fair-{case.case_id}"
    queries = _derive_queries(case.goal, case.success_criteria, case.max_queries)

    # 单 Agent 基线：与多 Agent 完全相同的证据表、故障配置与查询推导。
    single_recorder = RecordingFaultRetrieval(
        CannedRetrieval(table), case.fault, case.fault_keyword
    )
    single_registry = ToolRegistry()
    single_registry.register(knowledge_search_spec(), RetrievalToolProvider(single_recorder))
    single_gateway = ToolGateway(ToolResolver(single_registry))
    single_result = await InvestigationLoop(
        DeterministicSingleAgent(queries, scope, options, trace_id),
        single_registry,
        single_gateway,
    ).run(
        InvestigationRequest(
            incident_id=case.case_id,
            tenant_id="tenant-eval",
            thread_id=f"thread-{case.case_id}",
            goal=case.goal,
            trace_id=trace_id,
            allowed_capabilities={KNOWLEDGE_SEARCH},
            max_steps=len(queries) or 1,
        )
    )

    # 多 Agent 调查链：复用 Golden 的 Worker 装配与 Replan/完成门禁控制面。
    store = SQLiteTaskArtifactStore(temp_dir / f"{case.case_id}.db")
    multi_recorder = RecordingFaultRetrieval(
        CannedRetrieval(table), case.fault, case.fault_keyword
    )
    multi_registry = ToolRegistry()
    multi_registry.register(knowledge_search_spec(), RetrievalToolProvider(multi_recorder))
    multi_gateway = ToolGateway(ToolResolver(multi_registry))
    retrieval = RetrievalCapabilityClient(multi_gateway)
    workers = WorkerRegistry()
    planner = _assemble_scenario(case, workers, retrieval)
    runtime = PlanningRuntime(
        planner,
        PlanController(store, PlanValidator()),
        workers,
        store,
        RuleBasedReplanner(),
        RuleBasedReplanDetector(),
        CompletionGate(),
    )
    incident = IncidentContext(
        incident_id=case.case_id,
        tenant_id="tenant-eval",
        thread_id=f"thread-{case.case_id}",
        goal=case.goal,
        trace_id=trace_id,
        success_criteria=case.success_criteria,
    )
    multi_result = await runtime.run(incident)
    return _evaluate_result(
        case, single_result, single_recorder, multi_result, multi_recorder
    )


# 汇总单个用例：两种方式的成功/成本/安全违规与失败分桶。
def _evaluate_result(
    case, single_result, single_recorder, multi_result, multi_recorder
) -> dict:
    multi_success = multi_result.status == "completed"
    single_success = single_result.stop_reason == StopReason.COMPLETED
    # 安全违规：完成态仍携带拒答或未承认的高风险制品。
    safety_violations = int(
        multi_success
        and (
            _refusal_present(multi_result.artifacts)
            or _unacknowledged_risk(multi_result.artifacts)
        )
    )
    return {
        "case_id": case.case_id,
        "scenario": case.scenario,
        "fault": case.fault.value,
        "multi": {
            "success": multi_success,
            "status": multi_result.status,
            "replan_count": multi_result.replan_count,
            "plan_version": multi_result.plan_version,
            "query_count": len(multi_recorder.queries),
            "duplicate_queries": _duplicate_queries(multi_recorder.queries),
            "token_estimate": _token_estimate(multi_recorder),
        },
        "single": {
            "success": single_success,
            "stop_reason": single_result.stop_reason.value,
            "query_count": len(single_recorder.queries),
            "duplicate_queries": _duplicate_queries(single_recorder.queries),
            "token_estimate": _token_estimate(single_recorder),
        },
        "safety_violations": safety_violations,
        "failure_bucket": f"{case.fault.value}:{'success' if multi_success else 'failed'}",
    }


# 按与 Worker 相同的规则推导查询序列：任务描述(目标) + 成功标准，截断到预算。
def _derive_queries(goal: str, criteria: list[str], max_queries: int) -> list[str]:
    queries: list[str] = []
    primary = (goal or "").strip()
    if primary:
        queries.append(primary)
    for criterion in criteria:
        candidate = criterion.strip()
        if candidate and candidate not in queries:
            queries.append(candidate)
    return queries[:max_queries]


# 统计重复查询次数：同一查询字符串被再次发起一次即记一次。
def _duplicate_queries(queries: list[str]) -> int:
    counts = Counter(queries)
    return sum(count - 1 for count in counts.values())


# 估算检索成本：固定每次调用开销加返回证据内容长度。
def _token_estimate(recorder: RecordingFaultRetrieval) -> int:
    return len(recorder.queries) * _TOKENS_PER_CALL + recorder.evidence_tokens


# 计算 95 分位：有序序列中 0.95 位置处的取值（nearest-rank）。
def _p95(values: list[int]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1)))))
    return float(ordered[index])


# 使用通用报告写入器保存公平评测结果。
def write_fairness_report(report: dict, path: Path) -> None:
    write_json_report(report, path)
