import pytest

from flowfix_agent.planning.models import (
    Artifact,
    CommittedPlan,
    ReplanTrigger,
    TaskSpec,
)
from flowfix_agent.planning.replanning import RuleBasedReplanDetector, RuleBasedReplanner


def _plan(version: int = 1) -> CommittedPlan:
    return CommittedPlan(
        plan_id="plan-1",
        version=version,
        tasks=[
            TaskSpec(
                task_id="diagnose",
                description="diagnose",
                required_role="diagnosis",
                allowed_capabilities={"knowledge.search"},
            ),
            TaskSpec(
                task_id="resource",
                description="resource",
                required_role="resource_planning",
                dependencies=["diagnose"],
                allowed_capabilities={"knowledge.search"},
            ),
        ],
    )


def _artifact(
    task_id: str, worker_id: str, payload: dict, plan_version: int = 1
) -> Artifact:
    return Artifact(
        artifact_id=f"artifact-{task_id}",
        task_id=task_id,
        plan_version=plan_version,
        worker_id=worker_id,
        payload=payload,
        confidence=0.8,
    )


def _resource_unavailable_payload() -> dict:
    return {
        "resource_planning": {
            "primary_available": False,
            "confidence": 0.7,
            "missing_info": ["备件到货时间"],
        }
    }


# 验证资源不可用触发 resource_unavailable，并取消对应任务。
async def test_detector_raises_resource_unavailable():
    detector = RuleBasedReplanDetector()
    artifacts = [
        _artifact(
            "resource",
            "resource_planning",
            _resource_unavailable_payload(),
        )
    ]

    trigger = await detector.detect("incident", _plan(), {"resource": "completed"}, artifacts)

    assert trigger is not None
    assert trigger.trigger == "resource_unavailable"
    assert trigger.cancel_task_ids == ["resource"]


# 验证诊断标记冲突触发 artifact_conflict。
async def test_detector_raises_artifact_conflict():
    detector = RuleBasedReplanDetector()
    artifacts = [
        _artifact(
            "diagnose",
            "diagnosis",
            {"diagnosis": {"conflict": "诊断结论与影响评估相悖"}},
        )
    ]

    trigger = await detector.detect("incident", _plan(), {"diagnose": "completed"}, artifacts)

    assert trigger is not None
    assert trigger.trigger == "artifact_conflict"
    assert trigger.cancel_task_ids == ["diagnose"]


# 验证诊断标记新证据推翻假设触发 new_evidence。
async def test_detector_raises_new_evidence():
    detector = RuleBasedReplanDetector()
    artifacts = [
        _artifact(
            "diagnose",
            "diagnosis",
            {"diagnosis": {"hypothesis_revised": "新日志显示为磁盘故障而非电源故障"}},
        )
    ]

    trigger = await detector.detect("incident", _plan(), {"diagnose": "completed"}, artifacts)

    assert trigger is not None
    assert trigger.trigger == "new_evidence"
    assert trigger.cancel_task_ids == ["diagnose"]


# 验证全部标记为空时检测器返回 None，不触发重规划。
async def test_detector_returns_none_when_no_signal():
    detector = RuleBasedReplanDetector()
    artifacts = [
        _artifact(
            "resource",
            "resource_planning",
            {"resource_planning": {"primary_available": True}},
        ),
        _artifact(
            "diagnose",
            "diagnosis",
            {"diagnosis": {"hypothesis_revised": None, "conflict": None}},
        ),
    ]

    trigger = await detector.detect("incident", _plan(), {}, artifacts)

    assert trigger is None


# 验证只检查当前计划版本制品：旧版本残留标记不会再次触发。
async def test_detector_ignores_stale_version_artifacts():
    detector = RuleBasedReplanDetector()
    stale = _artifact(
        "diagnose",
        "diagnosis",
        {"diagnosis": {"hypothesis_revised": "旧版本标记"}},
        plan_version=1,
    )

    trigger = await detector.detect("incident", _plan(version=2), {}, [stale])

    assert trigger is None


# 验证 enabled 子集开关：禁用 resource_unavailable 时该信号不触发。
async def test_detector_honors_enabled_subset():
    detector = RuleBasedReplanDetector(enabled={"new_evidence"})
    artifacts = [_artifact("resource", "resource_planning", _resource_unavailable_payload())]

    trigger = await detector.detect("incident", _plan(), {}, artifacts)

    assert trigger is None


# 验证内容触发器补丁：取消原任务、新增「-revised」任务并保留原依赖与能力。
async def test_replanner_patch_for_trigger():
    replanner = RuleBasedReplanner()
    trigger = ReplanTrigger(
        trigger="resource_unavailable",
        reason="关键备件不可用",
        cancel_task_ids=["resource"],
    )

    patch = await replanner.replan("incident", _plan(version=2), [], trigger=trigger)

    assert patch.expected_plan_version == 2
    assert patch.cancel_task_ids == ["resource"]
    assert [task.task_id for task in patch.add_tasks] == ["resource-revised"]
    revised = patch.add_tasks[0]
    assert revised.required_role == "resource_planning"
    # 原依赖 diagnose 未被取消，保留为依赖；能力集沿用且不含写能力。
    assert revised.dependencies == ["diagnose"]
    assert revised.allowed_capabilities == {"knowledge.search"}
    assert "assignment.create" not in revised.allowed_capabilities


# 验证失败任务兜底补丁：取消失败任务及其下游并新增 recovery 任务。
async def test_replanner_patch_for_failed_tasks():
    replanner = RuleBasedReplanner()

    patch = await replanner.replan("incident", _plan(version=1), ["diagnose"])

    # resource 依赖 diagnose，诊断失败后其制品缺失，一并取消，避免悬空依赖。
    assert patch.cancel_task_ids == ["diagnose", "resource"]
    assert [task.task_id for task in patch.add_tasks] == ["recovery"]
    assert patch.add_tasks[0].required_role == "diagnosis"
    assert patch.expected_plan_version == 1


# 验证失败任务的下游级联取消：恢复任务沿用失败任务的角色。
async def test_replanner_patch_for_failed_task_uses_failed_role():
    plan = CommittedPlan(
        plan_id="plan-2",
        version=1,
        tasks=[
            TaskSpec(
                task_id="impact",
                description="impact",
                required_role="impact_safety",
                allowed_capabilities={"knowledge.search"},
            ),
            TaskSpec(
                task_id="diagnose",
                description="diagnose",
                required_role="diagnosis",
                dependencies=["impact"],
                allowed_capabilities={"knowledge.search"},
            ),
        ],
    )
    replanner = RuleBasedReplanner()

    patch = await replanner.replan("incident", plan, ["impact"])

    assert patch.cancel_task_ids == ["diagnose", "impact"]
    assert patch.add_tasks[0].required_role == "impact_safety"


# 验证补丁中新增任务角色必须已注册：未配置的触发器类型直接报 KeyError。
async def test_replanner_unconfigured_trigger_type_fails():
    # 自定义 role_mapping 未配置 new_evidence，命中该触发器时抛 KeyError。
    replanner = RuleBasedReplanner(role_mapping={"artifact_conflict": "diagnosis"})
    trigger = ReplanTrigger(trigger="new_evidence", reason="x", cancel_task_ids=["diagnose"])

    with pytest.raises(KeyError):
        await replanner.replan("incident", _plan(), [], trigger=trigger)
