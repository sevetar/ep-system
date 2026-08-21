import pytest

from flowfix_agent.knowledge.models import SourceType
from flowfix_agent.planning.models import IncidentContext, TaskSpec
from flowfix_agent.planning.workers.diagnosis import (
    DiagnosisHypothesis,
    DiagnosisResult,
    DiagnosisValidationError,
    DiagnosisWorker,
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

    def __init__(self, result: DiagnosisResult | None = None) -> None:
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
        task_id="diagnose",
        description=description,
        required_role="diagnosis",
    )


# 验证 Worker 产出结构化 Artifact：引用合法、证据重排、缺失信息合并。
async def test_worker_produces_sourced_artifact():
    retrieval = FakeRetrieval(
        {"诊断DEV-1": [_evidence("chunk-a")], "链路": [_evidence("chunk-b")]}
    )
    result = DiagnosisResult(
        conclusion="根因为组件 A 故障。",
        confidence=0.7,
        hypotheses=[
            DiagnosisHypothesis(
                hypothesis_id="h1",
                title="组件 A 故障",
                summary="证据支持。",
                supporting_evidence=[1],
                opposing_evidence=[2],
                confidence=0.7,
                missing_info=["备件数据"],
            )
        ],
        missing_info=["备件数据"],
    )
    worker = DiagnosisWorker(retrieval, FakeGenerator(result), max_queries=3)

    artifact = await worker.execute(
        _incident("诊断DEV-1", ["链路"]), _task(""), []
    )

    assert artifact.worker_id == "diagnosis"
    assert artifact.confidence == 0.7
    assert artifact.evidence_refs == ["chunk-a", "chunk-b"]
    payload = artifact.payload
    assert payload["evidence_count"] == 2
    assert payload["queries"] == ["诊断DEV-1", "链路"]
    assert payload["missing_info"] == ["备件数据"]
    assert [item["citation_id"] for item in payload["evidence"]] == [1, 2]
    assert retrieval.chain_and_role == [
        ("investigation", "diagnosis-worker"),
        ("investigation", "diagnosis-worker"),
    ]


# 验证 Worker 按 max_queries 截断查询数量，不超出检索预算。
async def test_worker_respects_query_budget():
    retrieval = FakeRetrieval({})
    worker = DiagnosisWorker(retrieval, FakeGenerator(), max_queries=3)

    artifact = await worker.execute(
        _incident("诊断", ["c1", "c2", "c3", "c4", "c5"]), _task("诊断"), []
    )

    assert retrieval.calls == 3
    assert len(artifact.payload["queries"]) == 3


# 验证 Worker 对非法引用 fail-closed：假设引用未知证据编号时抛错。
async def test_worker_fail_closed_on_bad_citation():
    retrieval = FakeRetrieval({"诊断": [_evidence("chunk-a")]})
    bad = DiagnosisResult(
        conclusion="结论",
        confidence=0.5,
        hypotheses=[
            DiagnosisHypothesis(
                hypothesis_id="h1",
                title="假设",
                summary="说明",
                supporting_evidence=[9],
                confidence=0.5,
            )
        ],
    )
    worker = DiagnosisWorker(retrieval, FakeGenerator(bad), max_queries=3)

    with pytest.raises(DiagnosisValidationError):
        await worker.execute(_incident("诊断", []), _task("诊断"), [])


# 验证空证据时 fail-closed：不调用生成器，产出拒答 Artifact。
async def test_worker_fail_closed_on_empty_evidence():
    retrieval = FakeRetrieval({})
    generator = FakeGenerator()
    worker = DiagnosisWorker(retrieval, generator, max_queries=3)

    artifact = await worker.execute(
        _incident("诊断DEV-1", []), _task("诊断DEV-1"), []
    )

    assert generator.calls == 0
    assert artifact.confidence == 0
    assert artifact.evidence_refs == []
    assert artifact.payload["missing_info"] == ["诊断DEV-1"]
    assert artifact.payload["diagnosis"]["conclusion"].find("证据不足") != -1
    assert artifact.payload["diagnosis"]["hypotheses"] == []
