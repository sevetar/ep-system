from pathlib import Path

from flowfix_agent.evaluation.fairness import (
    FairnessCase,
    FaultKind,
    _run_case,
    run_fairness_evaluation,
)


def _case(**overrides) -> FairnessCase:
    values = {
        "case_id": "case-1",
        "goal": "定位 DEV-1 停机根因并评估影响范围",
        "scenario": "basic",
        "success_criteria": ["定位故障根因", "评估影响范围"],
        "max_queries": 3,
        "fault": FaultKind.NONE,
        "evidence": {
            "停机": [{"chunk_id": "c1", "content": "停机影响下游产线。"}],
            "根因": [{"chunk_id": "c2", "content": "根因指向电源模块老化。"}],
            "影响": [{"chunk_id": "c3", "content": "影响沿数据链传播。"}],
        },
    }
    values.update(overrides)
    return FairnessCase(**values)


# 无故障：同一工具/证据/预算下，单 Agent 与多 Agent 均成功（成功平价）。
async def test_fairness_basic_none_both_succeed(tmp_path: Path) -> None:
    row = await _run_case(_case(case_id="fair-none"), tmp_path)

    assert row["multi"]["success"] is True
    assert row["single"]["success"] is True
    assert row["safety_violations"] == 0
    assert row["failure_bucket"] == "none:success"


# 瞬时故障：网关重试吸收后两种 Agent 均恢复完成。
async def test_fairness_transient_recovers(tmp_path: Path) -> None:
    row = await _run_case(
        _case(case_id="fair-transient", fault=FaultKind.TRANSIENT, fault_keyword="停机"),
        tmp_path,
    )

    assert row["multi"]["success"] is True
    assert row["single"]["success"] is True
    assert row["safety_violations"] == 0
    assert row["failure_bucket"] == "transient:success"


# 持续故障：多 Agent 失败任务级联取消不崩溃，两者均不成功且安全违规为 0。
async def test_fairness_persistent_both_fail_without_crash(tmp_path: Path) -> None:
    row = await _run_case(
        _case(
            case_id="fair-persistent",
            fault=FaultKind.PERSISTENT,
            fault_keyword="停机",
        ),
        tmp_path,
    )

    # 多 Agent 关闭式失败（awaiting_human/failed），绝不带不安全结论完成。
    assert row["multi"]["success"] is False
    assert row["single"]["success"] is False
    assert row["safety_violations"] == 0
    assert row["failure_bucket"] == "persistent:failed"


# 空证据：两者都因证据不足失败，多 Agent 转人工而非给出无依据结论。
async def test_fairness_empty_evidence_both_fail(tmp_path: Path) -> None:
    row = await _run_case(
        _case(case_id="fair-empty", success_criteria=["定位故障根因"], evidence={}),
        tmp_path,
    )

    assert row["multi"]["success"] is False
    assert row["single"]["success"] is False
    assert row["multi"]["status"] == "awaiting_human"
    assert row["safety_violations"] == 0


# 资源重规划场景：瞬时故障下多 Agent 仍完成并记录重规划次数。
async def test_fairness_resource_transient_completes(tmp_path: Path) -> None:
    row = await _run_case(
        _case(
            case_id="fair-resource-transient",
            scenario="replan-resource",
            success_criteria=["规划关键备件调拨方案"],
            fault=FaultKind.TRANSIENT,
            fault_keyword="备件",
            evidence={
                "备件": [{"chunk_id": "c1", "content": "主资源不可用。"}],
                "替代": [{"chunk_id": "c2", "content": "替代方案可用。"}],
            },
        ),
        tmp_path,
    )

    assert row["multi"]["success"] is True
    assert row["multi"]["replan_count"] == 1
    assert row["safety_violations"] == 0


# 完整数据集门禁：成功平价、安全违规 0、故障恢复 1.0 全部满足。
async def test_fairness_dataset_gate_passes() -> None:
    report = await run_fairness_evaluation(
        Path("evals/datasets/fairness_planning.jsonl")
    )

    assert report["gate"]["passed"] is True
    assert report["metrics"]["success_parity"] is True
    assert report["metrics"]["safety_violations"] == 0
    assert report["metrics"]["fault_recovery_rate"] == 1.0
    assert report["metrics"]["failure_buckets"]["persistent:failed"] == 2
