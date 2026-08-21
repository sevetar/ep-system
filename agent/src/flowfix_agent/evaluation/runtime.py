from __future__ import annotations

import platform
import tempfile
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel

from flowfix_agent.core.errors import DependencyUnavailableError
from flowfix_agent.dispatch.adapters.decision_repository import InMemoryDispatchDecisionRepository
from flowfix_agent.dispatch.adapters.fake_tools import FakeDispatchToolAdapter
from flowfix_agent.dispatch.adapters.skill_registry import FileDispatchSkillRegistry
from flowfix_agent.dispatch.application.service import DispatchDecisionService
from flowfix_agent.dispatch.domain.models import (
    DispatchRequest,
    WorkerSnapshot,
    WorkOrderPriority,
    WorkOrderSnapshot,
)
from flowfix_agent.dispatch.runtime.errors import ToolAccessDeniedError
from flowfix_agent.dispatch.runtime.graph import DispatchAgentRuntime
from flowfix_agent.dispatch.runtime.middleware import DispatchToolGateway
from flowfix_agent.dispatch.runtime.models import (
    ApprovalDecision,
    DispatchRuntimeInput,
    RequestContext,
    RuntimeStatus,
    ToolName,
)
from flowfix_agent.dispatch.skills.loader import DispatchSkillLoader
from flowfix_agent.dispatch.skills.manifest import DispatchSkill
from flowfix_agent.evaluation.common import (
    boolean_rate,
    load_jsonl_dataset,
    write_json_report,
)


# 枚举 M4 固定集覆盖的自动、审批、无候选、恢复和越权场景。
class RuntimeEvaluationAction(StrEnum):
    AUTO = "auto"
    APPROVE = "approve"
    DENY = "deny"
    NO_CANDIDATE = "no_candidate"
    RECOVER_VERIFY = "recover_verify"
    READ_ONLY_BLOCKED = "read_only_blocked"


# 描述一条运行时评测场景及其预期状态和副作用数量。
class RuntimeEvaluationCase(BaseModel):
    case_id: str
    description: str
    action: RuntimeEvaluationAction
    expected_status: RuntimeStatus
    expected_assignment_side_effects: int
    expected_audit_side_effects: int
    expected_interrupted: bool = False
    expected_blocked: bool = False
    expected_checkpoint_recovery: bool = False


# 使用通用 JSONL 加载器读取 M4 运行时评测集。
def load_runtime_dataset(path: Path) -> list[RuntimeEvaluationCase]:
    return load_jsonl_dataset(path, RuntimeEvaluationCase, "dispatch runtime")


# 依次执行全部 M4 场景并汇总暂停恢复、幂等和权限门禁指标。
async def run_runtime_evaluation(
    dataset_path: Path,
    builtin_directory: Path,
) -> dict:
    cases = load_runtime_dataset(dataset_path)
    rows: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="flowfix-runtime-eval-") as temp_dir:
        for case in cases:
            row = await _run_case(case, Path(temp_dir), builtin_directory)
            rows.append(row)
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "milestone": "M4",
        "dataset": str(dataset_path),
        "runtime": {
            "python": platform.python_version(),
            "checkpointer": "InMemorySaver",
            "external_services_used": [],
        },
        "metrics": {
            "cases": len(rows),
            "scenario_pass_rate": boolean_rate(rows, "passed"),
            "duplicate_assignment_side_effect_count": sum(
                row["assignment_side_effects"]
                > row["expected_assignment_side_effects"]
                for row in rows
            ),
            "pause_resume_correct_rate": boolean_rate(
                [row for row in rows if row["expected_interrupted"]], "passed"
            ),
            "checkpoint_recovery_correct_rate": boolean_rate(
                [row for row in rows if row["expected_checkpoint_recovery"]],
                "passed",
            ),
            "skill_write_guard_correct_rate": boolean_rate(
                [row for row in rows if row["expected_blocked"]], "passed"
            ),
        },
        "case_results": rows,
        "gate": {
            "passed": all(row["passed"] for row in rows),
            "criteria": {
                "scenario_pass_rate": 1.0,
                "duplicate_assignment_side_effect_count": 0,
                "pause_resume_correct_rate": 1.0,
                "checkpoint_recovery_correct_rate": 1.0,
                "skill_write_guard_correct_rate": 1.0,
            },
        },
    }


# 构造隔离的 Fake 运行时并执行一条固定评测场景。
async def _run_case(
    case: RuntimeEvaluationCase,
    temp_dir: Path,
    builtin_directory: Path,
) -> dict:
    event_id = f"event-{case.case_id}"
    dispatch_id = f"dispatch-{case.case_id}"
    now = datetime(2026, 8, 4, 8, 0, tzinfo=UTC)
    priority = (
        WorkOrderPriority.URGENT
        if case.action in {RuntimeEvaluationAction.APPROVE, RuntimeEvaluationAction.DENY}
        else WorkOrderPriority.NORMAL
    )
    order = WorkOrderSnapshot(
        work_order_id=f"wo-{case.case_id}",
        tenant_id="tenant-eval",
        device_id="device-eval",
        region="east",
        required_skills=["plc"],
        priority=priority,
        version=1,
        captured_at=now,
    )
    worker = WorkerSnapshot(
        worker_id="worker-eval",
        tenant_id="tenant-eval",
        region="east",
        skills={"plc": 1.0},
        available=case.action != RuntimeEvaluationAction.NO_CANDIDATE,
        current_load=0,
        capacity=5,
        distance_km=1,
        sla_readiness=1.0,
        captured_at=now,
    )
    registry = FileDispatchSkillRegistry(temp_dir / f"{case.case_id}.json")
    loader = DispatchSkillLoader()
    for skill in loader.load_directory(builtin_directory):
        registry.register(skill)
    if case.action == RuntimeEvaluationAction.READ_ONLY_BLOCKED:
        read_only = _read_only_skill(loader.load(builtin_directory / "balanced-v1.json"))
        registry.register(read_only)
        registry.activate(read_only.skill_id, read_only.skill_version)
    else:
        registry.activate("balanced", "1.0.0")
    adapter = FakeDispatchToolAdapter([order], [worker])
    gateway = DispatchToolGateway(adapter, max_attempts=2)
    runtime = DispatchAgentRuntime(
        DispatchDecisionService(registry, InMemoryDispatchDecisionRepository()),
        gateway,
    )
    runtime_input = DispatchRuntimeInput(
        request=DispatchRequest(
            dispatch_id=dispatch_id,
            event_id=event_id,
            tenant_id="tenant-eval",
            requested_at=now,
        ),
        work_order_id=order.work_order_id,
        context=RequestContext(
            trace_id=f"trace-{case.case_id}",
            tenant_id="tenant-eval",
            event_id=event_id,
            permissions=["dispatch:read", "dispatch:write", "dispatch:audit"],
            deadline=datetime.now(UTC) + timedelta(minutes=1),
        ),
    )
    thread_id = f"dispatch:tenant-eval:{dispatch_id}"
    interrupted = False
    blocked = False
    recovered = False
    status = RuntimeStatus.FAILED
    if case.action == RuntimeEvaluationAction.RECOVER_VERIFY:
        adapter.fail_next(ToolName.GET_ASSIGNMENT_OUTCOME, times=2)
    try:
        result = await runtime.start(runtime_input)
        interrupted = result.interrupted
        if case.action in {RuntimeEvaluationAction.APPROVE, RuntimeEvaluationAction.DENY}:
            result = await runtime.resume(
                thread_id,
                ApprovalDecision(
                    approved=case.action == RuntimeEvaluationAction.APPROVE,
                    reviewer_id="runtime-evaluator",
                    worker_id=(
                        "worker-eval"
                        if case.action == RuntimeEvaluationAction.APPROVE
                        else None
                    ),
                    reason="fixed M4 evaluation action",
                ),
            )
        status = result.status
    except DependencyUnavailableError:
        result = await runtime.retry(thread_id)
        status = result.status
        recovered = True
    except ToolAccessDeniedError:
        blocked = True

    assignment_side_effects = adapter.side_effect_counts[
        ToolName.CREATE_ASSIGNMENT.value
    ]
    audit_side_effects = adapter.side_effect_counts[
        ToolName.PUBLISH_DISPATCH_AUDIT.value
    ]
    passed = all(
        (
            status == case.expected_status,
            assignment_side_effects == case.expected_assignment_side_effects,
            audit_side_effects == case.expected_audit_side_effects,
            interrupted == case.expected_interrupted,
            blocked == case.expected_blocked,
            recovered == case.expected_checkpoint_recovery,
        )
    )
    return {
        "case_id": case.case_id,
        "status": status,
        "interrupted": interrupted,
        "blocked": blocked,
        "checkpoint_recovered": recovered,
        "assignment_side_effects": assignment_side_effects,
        "audit_side_effects": audit_side_effects,
        "expected_assignment_side_effects": case.expected_assignment_side_effects,
        "expected_interrupted": case.expected_interrupted,
        "expected_blocked": case.expected_blocked,
        "expected_checkpoint_recovery": case.expected_checkpoint_recovery,
        "tool_attempts": dict(sorted(adapter.call_counts.items())),
        "passed": passed,
    }


# 从基准策略派生禁止业务写入的只读 Skill。
def _read_only_skill(base: DispatchSkill) -> DispatchSkill:
    payload = base.model_dump(mode="json", exclude={"content_hash", "status"})
    payload.update({"skill_id": "read-only", "skill_version": "1.0.0"})
    payload["tool_policy"]["allowed_write_tools"] = ["publish_dispatch_audit"]
    return DispatchSkill.model_validate(payload)


# 使用通用 JSON 报告写入器保存 M4 运行时评测结果。
def write_runtime_report(report: dict, path: Path) -> None:
    write_json_report(report, path)
