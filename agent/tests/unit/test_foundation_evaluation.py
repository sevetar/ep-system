from flowfix_agent.evaluation.foundation import evaluate_router


def test_router_foundation_dataset_passes():
    report = evaluate_router("evals/datasets/router_phase_a.jsonl")

    assert report["gate"]["passed"] is True
    assert report["accuracy"] == 1
