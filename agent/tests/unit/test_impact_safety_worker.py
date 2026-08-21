import pytest

from flowfix_agent.knowledge.models import SourceType
from flowfix_agent.planning.models import IncidentContext, TaskSpec
from flowfix_agent.planning.workers.impact_safety import (
    ImpactSafetyResult,
    ImpactSafetyValidationError,
    ImpactSafetyWorker,
    ImpactScope,
    MandatoryCheck,
    RiskItem,
    RiskLevel,
    SafetyConstraint,
)
from flowfix_agent.retrieval.models import Evidence, EvidenceBundle, RetrievalMode


# 构造一条最小合法证据。
def _evidence(chunk_id: str) -> Evidence:
    return Evidence(
        citation_id=1,
        chunk_id=chunk_id,
        source_id=chunk_id,
        source_type=SourceType.PLATFORM_DOC,
        source_version="1.0.0",
        title="手册",
        section_path="",
        content=f"内容 {chunk_id}",
        score=0.9,
        estimated_tokens=10,
    )


# 构造只读检索包。
def _bundle(query: str, scope, evidence: list[Evidence]) -> EvidenceBundle:
    return EvidenceBundle(
        trace_id="t",
        original_query=query,
        retrieval_query=query,
        mode=RetrievalMode.HYBRID,
        scope=scope,
        candidates=[],
        selected_evidence=evidence,
        budget_used=0,
        sufficient=bool(evidence),
        latency_ms=0.0,
    )


# 只读检索桩：按查询返回固定证据，记录调用参数，无任何写方法。
class FakeRetrieval:
    def __init__(self, table: dict[str, list[Evidence]]) -> None:
        self.table = table
        self.calls = 0
        self.chain_and_role: list[tuple[str, str]] = []

    async def retrieve(self, query, scope, options, trace_id=None, *, chain, role):
        self.calls += 1
        self.chain_and_role.append((chain, role))
        return _bundle(query, scope, self.table.get(query, []))


# 生成器桩：返回固定结果并记录是否被调用。
class FakeGenerator:
    model = "fake"

    def __init__(self, result: ImpactSafetyResult | None = None) -> None:
        self.result = result
        self.calls = 0

    async def generate(self, incident, task, evidence):
        self.calls += 1
        if self.result is None:
            raise AssertionError("generator must not be called without evidence")
        return self.result


def _incident(goal: str, criteria: list[str]) -> IncidentContext:
    return IncidentContext(
        incident_id="incident-1",
        tenant_id="tenant-1",
        thread_id="thread-1",
        goal=goal,
        trace_id="trace-1",
        success_criteria=criteria,
    )


def _task(description: str) -> TaskSpec:
    return TaskSpec(
        task_id="impact",
        description=description,
        required_role="impact_safety",
    )


# 构造引用首个证据的合法评估结果。
def _valid_result(first: int) -> ImpactSafetyResult:
    return ImpactSafetyResult(
        overall_risk_level=RiskLevel.HIGH,
        confidence=0.8,
        impact_scopes=[
            ImpactScope(
                scope_id="s1",
                target="受影响设备",
                description="故障导致目标受影响。",
                supporting_evidence=[first],
            )
        ],
        risks=[
            RiskItem(
                risk_id="r1",
                title="影响扩大化",
                description="故障可能扩大影响范围。",
                severity=RiskLevel.HIGH,
                supporting_evidence=[first],
            )
        ],
        safety_constraints=[
            SafetyConstraint(
                constraint_id="c1",
                action="禁止带电检修。",
                rationale="防止人身伤害。",
                supporting_evidence=[first],
            )
        ],
        mandatory_checks=[
            MandatoryCheck(
                check_id="m1",
                item="处置前确认设备已隔离。",
                supporting_evidence=[first],
            )
        ],
        missing_info=["现场巡检数据"],
    )


# 验证 Worker 产出结构化 Artifact：影响项齐全、引用合法、证据重排、缺失信息合并。
async def test_worker_produces_sourced_artifact():
    retrieval = FakeRetrieval(
        {"评估影响": [_evidence("chunk-a")], "风险": [_evidence("chunk-b")]}
    )
    worker = ImpactSafetyWorker(
        retrieval, FakeGenerator(_valid_result(1)), max_queries=3
    )

    artifact = await worker.execute(
        _incident("评估影响", ["风险"]), _task(""), []
    )

    assert artifact.worker_id == "impact_safety"
    assert artifact.confidence == 0.8
    # 引用收集只包含被引用的证据；全部证据合并后编号重排为全局 1..N。
    assert artifact.evidence_refs == ["chunk-a"]
    payload = artifact.payload
    assert payload["evidence_count"] == 2
    assert payload["queries"] == ["评估影响", "风险"]
    assert payload["missing_info"] == ["现场巡检数据"]
    assert [item["citation_id"] for item in payload["evidence"]] == [1, 2]
    assert retrieval.chain_and_role == [
        ("investigation", "impact-safety-worker"),
        ("investigation", "impact-safety-worker"),
    ]


# 验证 Worker 按 max_queries 截断查询数量，不超出检索预算。
async def test_worker_respects_query_budget():
    retrieval = FakeRetrieval({})
    worker = ImpactSafetyWorker(retrieval, FakeGenerator(), max_queries=3)

    artifact = await worker.execute(
        _incident("评估", ["c1", "c2", "c3", "c4", "c5"]), _task("评估"), []
    )

    assert retrieval.calls == 3
    assert len(artifact.payload["queries"]) == 3


# 验证 Worker 对非法引用 fail-closed：影响项引用未知证据编号时抛错。
async def test_worker_fail_closed_on_bad_citation():
    retrieval = FakeRetrieval({"评估": [_evidence("chunk-a")]})
    bad = _valid_result(1).model_copy(deep=True)
    bad.risks[0].supporting_evidence = [9]
    worker = ImpactSafetyWorker(retrieval, FakeGenerator(bad), max_queries=3)

    with pytest.raises(ImpactSafetyValidationError):
        await worker.execute(_incident("评估", []), _task("评估"), [])


# 验证空证据时 fail-closed：不调用生成器，产出 unknown 拒答 Artifact。
async def test_worker_fail_closed_on_empty_evidence():
    retrieval = FakeRetrieval({})
    generator = FakeGenerator()
    worker = ImpactSafetyWorker(retrieval, generator, max_queries=3)

    artifact = await worker.execute(
        _incident("评估DEV-1", []), _task("评估DEV-1"), []
    )

    assert generator.calls == 0
    assert artifact.confidence == 0
    assert artifact.evidence_refs == []
    assert artifact.payload["missing_info"] == ["评估DEV-1"]
    assert artifact.payload["impact_safety"]["overall_risk_level"] == "unknown"
    assert artifact.payload["impact_safety"]["risks"] == []


# 验证 Worker 对缺失来源的影响项 fail-closed：无正证据时抛错。
async def test_worker_fail_closed_on_item_without_evidence():
    retrieval = FakeRetrieval({"评估": [_evidence("chunk-a")]})
    bad = _valid_result(1).model_copy(deep=True)
    bad.mandatory_checks[0].supporting_evidence = []
    worker = ImpactSafetyWorker(retrieval, FakeGenerator(bad), max_queries=3)

    with pytest.raises(ImpactSafetyValidationError):
        await worker.execute(_incident("评估", []), _task("评估"), [])


# 验证「不能降风险」：整体风险等级低于已识别风险的最高等级时抛错。
async def test_worker_rejects_lowered_risk_level():
    retrieval = FakeRetrieval({"评估": [_evidence("chunk-a")]})
    lowered = _valid_result(1).model_copy(deep=True)
    lowered.overall_risk_level = RiskLevel.LOW
    lowered.risks[0].severity = RiskLevel.CRITICAL
    worker = ImpactSafetyWorker(retrieval, FakeGenerator(lowered), max_queries=3)

    with pytest.raises(ImpactSafetyValidationError):
        await worker.execute(_incident("评估", []), _task("评估"), [])
