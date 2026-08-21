from __future__ import annotations

import platform
import tempfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from flowfix_agent.dispatch.adapters.decision_repository import InMemoryDispatchDecisionRepository
from flowfix_agent.dispatch.adapters.skill_registry import FileDispatchSkillRegistry
from flowfix_agent.dispatch.application.service import DispatchDecisionService
from flowfix_agent.dispatch.domain.models import (
    DispatchOutcome,
    DispatchRequest,
    WorkerSnapshot,
    WorkOrderSnapshot,
    WorkOrderStatus,
)
from flowfix_agent.dispatch.skills.loader import DispatchSkillLoader
from flowfix_agent.evaluation.common import (
    boolean_rate,
    load_jsonl_dataset,
    write_json_report,
)


# 描述评测用例在某个策略下的预期决策。
class ExpectedDecision(BaseModel):
    outcome: DispatchOutcome
    selected_worker_id: str | None = None


# 表示一条包含输入快照和多策略预期结果的评测用例。
class DispatchEvaluationCase(BaseModel):
    case_id: str
    description: str
    request: DispatchRequest
    order: WorkOrderSnapshot
    workers: list[WorkerSnapshot]
    expected: dict[str, ExpectedDecision]


# 使用通用 JSONL 加载器读取派单评测数据集。
def load_dispatch_dataset(path: Path) -> list[DispatchEvaluationCase]:
    return load_jsonl_dataset(path, DispatchEvaluationCase, "dispatch")


# 在固定数据集上运行全部内置策略并汇总质量门禁指标。
async def run_dispatch_evaluation(
    dataset_path: Path,
    builtin_directory: Path,
) -> dict:
    """在同一固定集上比较所有内置 Skill，不访问 ES 或其他外部组件。"""
    cases = load_dispatch_dataset(dataset_path)
    skills = DispatchSkillLoader().load_directory(builtin_directory)
    strategy_reports: dict[str, dict] = {}

    with tempfile.TemporaryDirectory(prefix="flowfix-dispatch-eval-") as temp_dir:
        for skill in skills:
            registry = FileDispatchSkillRegistry(Path(temp_dir) / f"{skill.skill_id}.json")
            for candidate in skills:
                registry.register(candidate)
            registry.activate(skill.skill_id, skill.skill_version)
            service = DispatchDecisionService(
                registry, InMemoryDispatchDecisionRepository()
            )
            rows = []
            decision_sample = None
            outcomes: Counter[str] = Counter()
            for case in cases:
                decision = await service.decide(case.request, case.order, case.workers)
                replay = await service.decide(case.request, case.order, case.workers)
                expected = case.expected[skill.skill_id]
                behavior_correct = (
                    decision.outcome == expected.outcome
                    and decision.selected_worker_id == expected.selected_worker_id
                )
                unsafe = _is_unsafe_assignment(case, decision)
                deterministic = (
                    decision.decision_id == replay.decision_id
                    and decision.decision_fingerprint == replay.decision_fingerprint
                )
                outcomes[decision.outcome.value] += 1
                if case.case_id == "normal_assignment":
                    decision_sample = decision.model_dump(mode="json")
                rows.append(
                    {
                        "case_id": case.case_id,
                        "outcome": decision.outcome,
                        "selected_worker_id": decision.selected_worker_id,
                        "behavior_correct": behavior_correct,
                        "unsafe_assignment": unsafe,
                        "deterministic_replay": deterministic,
                        "reason_complete": bool(decision.reasons),
                        "decision_id": decision.decision_id,
                        "input_fingerprint": decision.input_fingerprint,
                        "decision_fingerprint": decision.decision_fingerprint,
                    }
                )

            strategy_reports[skill.key] = {
                "skill_content_hash": skill.content_hash,
                "cases": len(rows),
                "behavior_accuracy": boolean_rate(rows, "behavior_correct"),
                "unsafe_assignment_count": sum(row["unsafe_assignment"] for row in rows),
                "deterministic_replay_rate": boolean_rate(rows, "deterministic_replay"),
                "duplicate_event_second_result_count": sum(
                    not row["deterministic_replay"] for row in rows
                ),
                "reason_complete_rate": boolean_rate(rows, "reason_complete"),
                "outcome_distribution": dict(sorted(outcomes.items())),
                "replayable_decision_sample": decision_sample,
                "case_results": rows,
            }

        lifecycle = await _evaluate_lifecycle(Path(temp_dir), skills, cases)

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "milestone": "M3",
        "dataset": str(dataset_path),
        "runtime": {"python": platform.python_version(), "external_services_used": []},
        "strategies": strategy_reports,
        "lifecycle": lifecycle,
        "gate": {
            "passed": all(
                report["behavior_accuracy"] == 1.0
                and report["unsafe_assignment_count"] == 0
                and report["deterministic_replay_rate"] == 1.0
                and report["duplicate_event_second_result_count"] == 0
                and report["reason_complete_rate"] == 1.0
                for report in strategy_reports.values()
            )
            and all(lifecycle.values()),
            "criteria": {
                "behavior_accuracy": 1.0,
                "unsafe_assignment_count": 0,
                "deterministic_replay_rate": 1.0,
                "duplicate_event_second_result_count": 0,
                "reason_complete_rate": 1.0,
                "skill_switch_isolation": True,
                "skill_rollback": True,
            },
        },
    }


# 验证策略切换隔离性和版本回滚行为。
async def _evaluate_lifecycle(
    temp_dir: Path,
    skills: list,
    cases: list[DispatchEvaluationCase],
) -> dict[str, bool]:
    registry = FileDispatchSkillRegistry(temp_dir / "lifecycle.json")
    for skill in skills:
        registry.register(skill)
    registry.activate("balanced", "1.0.0")
    service = DispatchDecisionService(registry, InMemoryDispatchDecisionRepository())
    case = next(item for item in cases if item.case_id == "strategy_tradeoff")
    prepared = service.prepare(case.request, case.order, case.workers)
    registry.activate("sla-first", "1.0.0")
    frozen_decision = await service.decide_prepared(prepared)
    switched = registry.get_active().skill_id == "sla-first"
    restored = registry.rollback()
    return {
        "skill_switch_isolation": switched and frozen_decision.skill_id == "balanced",
        "skill_rollback": restored.skill_id == "balanced",
    }


# 判断分配结果是否违反任一硬性安全条件。
def _is_unsafe_assignment(case: DispatchEvaluationCase, decision) -> bool:
    if decision.outcome != DispatchOutcome.ASSIGN:
        return False
    if any(
        exclusion.worker_id == decision.selected_worker_id
        for exclusion in decision.exclusions
    ):
        return True
    if case.order.status != WorkOrderStatus.PENDING_DISPATCH:
        return True
    selected = next(
        (worker for worker in case.workers if worker.worker_id == decision.selected_worker_id),
        None,
    )
    return selected is None or any(
        (
            selected.tenant_id != case.order.tenant_id,
            not selected.available,
            not selected.shift_active,
            selected.current_load >= selected.capacity,
            bool(set(case.order.required_skills) - set(selected.skills)),
        )
    )


# 使用通用报告写入器保存派单评测结果。
def write_dispatch_report(report: dict, path: Path) -> None:
    write_json_report(report, path)
