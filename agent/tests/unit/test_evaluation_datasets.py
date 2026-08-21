import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from flowfix_agent.evaluation.foundation import evaluate_router
from flowfix_agent.evaluation.qa import load_dataset
from flowfix_agent.knowledge.quality import WorkOrderKnowledgeQualityGate
from flowfix_agent.messaging.models import WorkOrderCompletedEvent

ROOT = Path(__file__).resolve().parents[2]
DATASETS = ROOT / "evals" / "datasets"
KNOWLEDGE_DOCS = ROOT.parent / "backend" / "docs"


def _jsonl(name: str) -> list[dict]:
    return [
        json.loads(line)
        for line in (DATASETS / name).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_rag_benchmark_has_fifty_unique_grounded_cases() -> None:
    cases = load_dataset(DATASETS / "flowfix_l2.jsonl")

    assert len(cases) == 50
    assert len({case.case_id for case in cases}) == len(cases)
    assert Counter(case.slice for case in cases) == {
        "single_document": 32,
        "multi_document": 10,
        "unanswerable": 8,
    }
    for case in cases:
        combined_sources = ""
        for source in case.relevant_sources:
            path = KNOWLEDGE_DOCS / source
            assert path.is_file(), f"{case.case_id}: missing source {source}"
            combined_sources += path.read_text(encoding="utf-8").lower()
        for term in case.expected_terms:
            assert term.lower() in combined_sources, (
                f"{case.case_id}: expected term is absent from labeled sources: {term}"
            )


def test_router_benchmark_is_balanced_and_has_no_dangerous_misroutes() -> None:
    report = evaluate_router(DATASETS / "router_phase_a.jsonl")

    assert report["total"] == 50
    assert min(report["class_distribution"].values()) >= 12
    assert report["macro_f1"] == 1.0
    assert report["dangerous_misroute_count"] == 0
    assert report["gate"]["passed"] is True


def test_knowledge_e2e_manifest_matches_quality_gate_and_relations() -> None:
    cases = _jsonl("knowledge_e2e_v1.jsonl")
    by_id = {case["case_id"]: case for case in cases}
    quality_gate = WorkOrderKnowledgeQualityGate()

    assert len(cases) == 10
    assert set(by_id) == {f"K{index:02d}" for index in range(1, 11)}
    for case in cases[:8]:
        payload = json.loads(
            json.dumps(case["event"], ensure_ascii=False).replace("{{RUN_ID}}", "dataset-test")
        )
        payload.update(
            event_id=f"dataset-test-{case['case_id']}",
            completed_at=datetime(2026, 8, 15, tzinfo=UTC),
            trace_id=f"dataset-test-{case['case_id']}",
        )
        event = WorkOrderCompletedEvent.model_validate(payload)
        sanitized, redacted_fields = quality_gate.sanitize(event)
        assessment = quality_gate.assess(sanitized, redacted_fields)
        expected_rejected = case["expected_statuses"] == ["rejected"]

        assert assessment.accepted is not expected_rejected
        assert set(case.get("expected_quality_issues", [])) <= set(assessment.issues)
        assert set(case.get("expected_redacted_fields", [])) <= set(redacted_fields)

    assert by_id["K09"]["replay_of"] == "K01"
    assert by_id["K10"]["revoke_of"] == "K02"
