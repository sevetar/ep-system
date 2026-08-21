from pathlib import Path

from flowfix_agent.evaluation.runtime import run_runtime_evaluation

DATASET = Path("evals/datasets/dispatch_m4.jsonl").resolve()
BUILTIN = Path("src/flowfix_agent/dispatch/skills/builtin").resolve()


# 验证 M4 运行时固定集的全部质量门禁均通过。
async def test_m4_runtime_golden_set_passes_all_gates() -> None:
    report = await run_runtime_evaluation(DATASET, BUILTIN)

    assert report["gate"]["passed"] is True
    assert report["metrics"] == {
        "cases": 6,
        "scenario_pass_rate": 1.0,
        "duplicate_assignment_side_effect_count": 0,
        "pause_resume_correct_rate": 1.0,
        "checkpoint_recovery_correct_rate": 1.0,
        "skill_write_guard_correct_rate": 1.0,
    }
