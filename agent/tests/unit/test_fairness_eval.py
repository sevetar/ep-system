import pytest

from flowfix_agent.core.models import RequestScope
from flowfix_agent.evaluation.fairness import (
    DeterministicSingleAgent,
    FaultKind,
    RecordingFaultRetrieval,
    _derive_queries,
    _duplicate_queries,
    _p95,
    _token_estimate,
)
from flowfix_agent.evaluation.golden import _build_table
from flowfix_agent.evaluation.impact_safety import CannedEvidenceItem, CannedRetrieval
from flowfix_agent.investigation.models import StopReason
from flowfix_agent.retrieval.models import RetrievalOptions
from flowfix_agent.tools.models import ToolObservation


def _recorder(fault: FaultKind = FaultKind.NONE, keyword: str | None = None):
    raw = {"备件": [CannedEvidenceItem(chunk_id="c1", content="备件供应说明。")]}
    recorder = RecordingFaultRetrieval(CannedRetrieval(_build_table(raw)), fault, keyword)
    scope = RequestScope(tenant_id="tenant-eval", visibility="tenant")
    options = RetrievalOptions()
    return recorder, scope, options


# 无故障且关键词不命中时原样透传并记录查询。
async def test_recorder_passthrough_when_keyword_unmatched():
    rec, scope, options = _recorder(FaultKind.PERSISTENT, "不存在")

    bundle = await rec.retrieve("关键备件", scope, options)

    assert bundle.selected_evidence
    assert rec.failures == 0
    assert rec.queries == ["关键备件"]
    assert rec.evidence_tokens == len("备件供应说明。")


# 瞬时故障：首次命中失败，随后调用恢复并记录证据规模。
async def test_recorder_transient_failure_recovers():
    rec, scope, options = _recorder(FaultKind.TRANSIENT, "备件")

    with pytest.raises(ConnectionError):
        await rec.retrieve("关键备件", scope, options)
    bundle = await rec.retrieve("关键备件", scope, options)

    assert rec.failures == 1
    assert rec.queries == ["关键备件", "关键备件"]
    assert bundle.selected_evidence
    assert rec.evidence_tokens == len("备件供应说明。")


# 持续故障：命中关键词的每次查询都失败。
async def test_recorder_persistent_failure_always_raises():
    rec, scope, options = _recorder(FaultKind.PERSISTENT, "备件")

    with pytest.raises(ConnectionError):
        await rec.retrieve("关键备件", scope, options)
    with pytest.raises(ConnectionError):
        await rec.retrieve("关键备件", scope, options)

    assert rec.failures == 2


def _scope_options():
    scope = RequestScope(tenant_id="tenant-eval", visibility="tenant")
    return scope, RetrievalOptions()


# 单 Agent 决策器依次发起查询，耗尽后宣告证据不足。
async def test_single_agent_decides_query_sequence():
    scope, options = _scope_options()
    agent = DeterministicSingleAgent(["q1", "q2"], scope, options, "tr")

    first = await agent.decide(None, [], [])
    assert first.tool_call is not None
    assert first.tool_call.arguments["query"] == "q1"

    second = await agent.decide(None, [], [])
    assert second.tool_call.arguments["query"] == "q2"

    exhausted = await agent.decide(None, [], [])
    assert exhausted.tool_call is None
    assert exhausted.stop_reason == StopReason.INSUFFICIENT_EVIDENCE


# 单 Agent 决策器命中证据后即完成并形成结论。
async def test_single_agent_stops_when_evidence_found():
    scope, options = _scope_options()
    agent = DeterministicSingleAgent(["q1"], scope, options, "tr")
    hit = ToolObservation(
        call_id="c1",
        capability="knowledge.search",
        provider="p",
        success=True,
        payload={"selected_evidence": [{"chunk_id": "c1"}]},
    )

    decision = await agent.decide(None, [], [hit])

    assert decision.tool_call is None
    assert decision.stop_reason == StopReason.COMPLETED
    assert decision.conclusion


# 查询推导与 Worker 规则一致：目标优先、成功标准去重、按预算截断。
def test_derive_queries_matches_worker_rule():
    assert _derive_queries("定位根因", ["定位故障根因", "评估影响范围"], 3) == [
        "定位根因",
        "定位故障根因",
        "评估影响范围",
    ]
    assert _derive_queries("定位故障根因", ["定位故障根因"], 3) == ["定位故障根因"]
    assert _derive_queries("g", ["c1", "c2", "c3", "c4"], 3) == ["g", "c1", "c2"]
    assert _derive_queries("", ["c1"], 3) == ["c1"]


# 重复查询计数：同一查询再次发起一次记一次重复。
def test_duplicate_queries_counts():
    assert _duplicate_queries(["a", "b"]) == 0
    assert _duplicate_queries(["a", "a", "b"]) == 1
    assert _duplicate_queries(["a", "a", "a"]) == 2
    assert _duplicate_queries([]) == 0


# P95 取最近秩：有序序列 0.95 位置的值。
def test_p95_nearest_rank():
    assert _p95([]) == 0.0
    assert _p95([1]) == 1.0
    assert _p95([1, 2, 3, 4, 5]) == 5.0
    assert _p95([1, 1, 1, 1]) == 1.0


# 成本估算：每次调用固定开销加返回证据内容长度。
def test_token_estimate():
    rec, _, _ = _recorder()
    rec.queries = ["q1", "q2"]
    rec.evidence_tokens = 200

    assert _token_estimate(rec) == 2 * 50 + 200
