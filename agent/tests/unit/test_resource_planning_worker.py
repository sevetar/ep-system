import pytest

from flowfix_agent.knowledge.models import SourceType
from flowfix_agent.planning.models import IncidentContext, TaskSpec
from flowfix_agent.planning.workers.resource_planning import (
    ResourceAlternative,
    ResourceCandidate,
    ResourceConflict,
    ResourceKind,
    ResourcePlanningResult,
    ResourcePlanningValidationError,
    ResourcePlanningWorker,
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

    def __init__(self, result: ResourcePlanningResult | None = None) -> None:
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
        task_id="resource",
        description=description,
        required_role="resource_planning",
    )


# 构造引用首个证据的合法资源规划结果（备件可用、无冲突无替代）。
def _valid_result(first: int) -> ResourcePlanningResult:
    return ResourcePlanningResult(
        primary_available=True,
        confidence=0.8,
        candidates=[
            ResourceCandidate(
                candidate_id="c1",
                kind=ResourceKind.SPARE_PART,
                name="2.5 寸 SATA 硬盘",
                description="仓库库存充足，可即时领取。",
                available=True,
                supporting_evidence=[first],
            )
        ],
        conflicts=[],
        alternatives=[],
        missing_info=["备件到货时间"],
    )


# 验证 Worker 产出结构化 Artifact：候选齐全、引用合法、证据重排、缺失信息合并。
async def test_worker_produces_sourced_artifact():
    retrieval = FakeRetrieval(
        {"规划备件": [_evidence("chunk-a")], "人员": [_evidence("chunk-b")]}
    )
    worker = ResourcePlanningWorker(
        retrieval, FakeGenerator(_valid_result(1)), max_queries=3
    )

    artifact = await worker.execute(_incident("规划备件", ["人员"]), _task(""), [])

    assert artifact.worker_id == "resource_planning"
    assert artifact.confidence == 0.8
    # 引用收集只包含被引用的证据；全部证据合并后编号重排为全局 1..N。
    assert artifact.evidence_refs == ["chunk-a"]
    payload = artifact.payload
    assert payload["evidence_count"] == 2
    assert payload["queries"] == ["规划备件", "人员"]
    assert payload["missing_info"] == ["备件到货时间"]
    assert [item["citation_id"] for item in payload["evidence"]] == [1, 2]
    assert retrieval.chain_and_role == [
        ("investigation", "resource-planning-worker"),
        ("investigation", "resource-planning-worker"),
    ]


# 验证 Worker 按 max_queries 截断查询数量，不超出检索预算。
async def test_worker_respects_query_budget():
    retrieval = FakeRetrieval({})
    worker = ResourcePlanningWorker(retrieval, FakeGenerator(), max_queries=3)

    artifact = await worker.execute(
        _incident("规划", ["c1", "c2", "c3", "c4", "c5"]), _task("规划"), []
    )

    assert retrieval.calls == 3
    assert len(artifact.payload["queries"]) == 3


# 验证 Worker 对非法引用 fail-closed：候选引用未知证据编号时抛错。
async def test_worker_fail_closed_on_bad_citation():
    retrieval = FakeRetrieval({"规划备件": [_evidence("chunk-a")]})
    bad = _valid_result(1).model_copy(deep=True)
    bad.candidates[0].supporting_evidence = [9]
    worker = ResourcePlanningWorker(retrieval, FakeGenerator(bad), max_queries=3)

    with pytest.raises(ResourcePlanningValidationError):
        await worker.execute(_incident("规划备件", []), _task("规划备件"), [])


# 验证空证据时 fail-closed：不调用生成器，产出无主资源可用的拒答 Artifact。
async def test_worker_fail_closed_on_empty_evidence():
    retrieval = FakeRetrieval({})
    generator = FakeGenerator()
    worker = ResourcePlanningWorker(retrieval, generator, max_queries=3)

    artifact = await worker.execute(
        _incident("规划DEV-9", []), _task("规划DEV-9"), []
    )

    assert generator.calls == 0
    assert artifact.confidence == 0
    assert artifact.evidence_refs == []
    assert artifact.payload["missing_info"] == ["规划DEV-9"]
    assert artifact.payload["resource_planning"]["primary_available"] is False
    assert artifact.payload["resource_planning"]["candidates"] == []
    assert artifact.payload["resource_planning"]["conflicts"] == []


# 验证 Worker 对缺失来源的候选 fail-closed：无正证据时抛错。
async def test_worker_fail_closed_on_item_without_evidence():
    retrieval = FakeRetrieval({"规划备件": [_evidence("chunk-a")]})
    bad = _valid_result(1).model_copy(deep=True)
    bad.candidates[0].supporting_evidence = []
    worker = ResourcePlanningWorker(retrieval, FakeGenerator(bad), max_queries=3)

    with pytest.raises(ResourcePlanningValidationError):
        await worker.execute(_incident("规划备件", []), _task("规划备件"), [])


# 验证主资源不可用时：必须带冲突与替代方案，并保守判定 primary_available=false。
async def test_worker_keeps_unavailable_result_with_conflicts():
    retrieval = FakeRetrieval(
        {"规划备件": [_evidence("chunk-a")], "替代": [_evidence("chunk-b")]}
    )
    first = 1
    unavailable = ResourcePlanningResult(
        primary_available=False,
        confidence=0.7,
        candidates=[
            ResourceCandidate(
                candidate_id="c1",
                kind=ResourceKind.SPARE_PART,
                name="电源模块",
                description="库存在途未到。",
                available=False,
                supporting_evidence=[first],
            )
        ],
        conflicts=[
            ResourceConflict(
                conflict_id="cf1",
                resource_id="r1",
                reason="关键备件库存不足。",
                supporting_evidence=[first],
            )
        ],
        alternatives=[
            ResourceAlternative(
                alternative_id="a1",
                resource_id="r1",
                alternative_name="上代兼容电源模块",
                description="接口兼容，可经评估后临时替代。",
                supporting_evidence=[2],
            )
        ],
        missing_info=["备件到货时间"],
    )
    worker = ResourcePlanningWorker(
        retrieval, FakeGenerator(unavailable), max_queries=3
    )

    artifact = await worker.execute(_incident("规划备件", ["替代"]), _task(""), [])

    payload = artifact.payload
    assert payload["resource_planning"]["primary_available"] is False
    assert len(payload["resource_planning"]["conflicts"]) == 1
    assert len(payload["resource_planning"]["alternatives"]) == 1
    # 引用收集包含备件与替代两个证据源。
    assert set(artifact.evidence_refs) == {"chunk-a", "chunk-b"}
