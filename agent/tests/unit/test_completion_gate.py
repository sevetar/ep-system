import pytest

from flowfix_agent.planning.completion import (
    CompletionGate,
    WritePolicy,
    build_dispatch_proposal,
)
from flowfix_agent.planning.models import (
    Artifact,
    CommittedPlan,
    DispatchProposal,
    IncidentContext,
    TaskSpec,
)


def _incident(**overrides) -> IncidentContext:
    values = {
        "incident_id": "i1",
        "tenant_id": "t1",
        "thread_id": "th1",
        "goal": "定位并处置故障",
        "trace_id": "tr1",
        "success_criteria": ["定位根因", "评估影响范围"],
    }
    values.update(overrides)
    return IncidentContext(**values)


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
                task_id="impact",
                description="impact",
                required_role="impact_safety",
                allowed_capabilities={"knowledge.search"},
            ),
        ],
    )


def _artifact(task_id: str, worker_id: str, payload: dict) -> Artifact:
    return Artifact(
        artifact_id=f"artifact-{task_id}",
        task_id=task_id,
        plan_version=1,
        worker_id=worker_id,
        payload=payload,
        evidence_refs=["chunk-1"],
        confidence=0.8,
    )


def _diagnosis_payload(clean: bool = True) -> dict:
    if not clean:
        return {"diagnosis": {"confidence": 0, "hypotheses": [], "conclusion": "拒答"}}
    return {
        "diagnosis": {
            "confidence": 0.8,
            "hypotheses": [{"hypothesis_id": "h1", "title": "根因"}],
            "conclusion": "电源模块故障",
        }
    }


def _impact_payload(risk: str = "medium", with_safety: bool = True) -> dict:
    payload = {
        "impact_safety": {
            "overall_risk_level": risk,
            "impact_scopes": [{"scope_id": "s1", "target": "下游产线"}],
        }
    }
    if with_safety:
        payload["impact_safety"]["safety_constraints"] = [
            {"constraint_id": "c1", "action": "禁止带电作业"}
        ]
    return payload


# 验证全部条件满足时门禁批准完成。
def test_gate_approves_complete():
    gate = CompletionGate()
    decision = gate.evaluate(
        _incident(),
        _plan(),
        {"diagnose": "completed", "impact": "completed"},
        [
            _artifact("diagnose", "diagnosis", _diagnosis_payload()),
            _artifact("impact", "impact_safety", _impact_payload()),
        ],
    )

    assert decision.approved is True
    assert decision.reasons == []


# 验证存在未完成任务时门禁拒绝完成（不能提前完成）。
def test_gate_rejects_pending_task():
    gate = CompletionGate()
    decision = gate.evaluate(
        _incident(),
        _plan(),
        {"diagnose": "completed", "impact": "pending"},
        [_artifact("diagnose", "diagnosis", _diagnosis_payload())],
    )

    assert decision.approved is False
    assert any("未完成任务" in reason for reason in decision.reasons)


# 验证计划任务缺少制品时门禁拒绝完成。
def test_gate_rejects_missing_artifact():
    gate = CompletionGate()
    decision = gate.evaluate(
        _incident(),
        _plan(),
        {"diagnose": "completed", "impact": "completed"},
        [_artifact("diagnose", "diagnosis", _diagnosis_payload())],
    )

    assert decision.approved is False
    assert any("缺少制品" in reason for reason in decision.reasons)


# 验证拒答制品（证据不足）阻断完成，转人工补充证据。
def test_gate_rejects_refusal_artifact():
    gate = CompletionGate()
    decision = gate.evaluate(
        _incident(),
        _plan(),
        {"diagnose": "completed", "impact": "completed"},
        [
            _artifact("diagnose", "diagnosis", _diagnosis_payload(clean=False)),
            _artifact("impact", "impact_safety", _impact_payload()),
        ],
    )

    assert decision.approved is False
    assert any("拒答制品" in reason for reason in decision.reasons)


# 验证高风险未被安全约束覆盖时门禁拒绝完成。
def test_gate_rejects_unacknowledged_high_risk():
    gate = CompletionGate()
    decision = gate.evaluate(
        _incident(),
        _plan(),
        {"diagnose": "completed", "impact": "completed"},
        [
            _artifact("diagnose", "diagnosis", _diagnosis_payload()),
            _artifact(
                "impact", "impact_safety", _impact_payload(risk="critical", with_safety=False)
            ),
        ],
    )

    assert decision.approved is False
    assert any("高风险" in reason for reason in decision.reasons)


# 验证成功标准未被覆盖时门禁拒绝完成（资源标准但无资源制品）。
def test_gate_rejects_uncovered_criterion():
    gate = CompletionGate()
    incident = _incident(success_criteria=["定位根因", "备件调拨方案"])
    decision = gate.evaluate(
        incident,
        _plan(),
        {"diagnose": "completed", "impact": "completed"},
        [
            _artifact("diagnose", "diagnosis", _diagnosis_payload()),
            _artifact("impact", "impact_safety", _impact_payload()),
        ],
    )

    assert decision.approved is False
    assert any("成功标准未覆盖" in reason for reason in decision.reasons)


# 验证任务携带写能力时门禁拒绝完成（WritePolicy 防线）。
def test_gate_rejects_write_capability():
    gate = CompletionGate()
    plan = _plan()
    plan.tasks[0].allowed_capabilities = {"assignment.create"}
    decision = gate.evaluate(
        _incident(),
        plan,
        {"diagnose": "completed", "impact": "completed"},
        [
            _artifact("diagnose", "diagnosis", _diagnosis_payload()),
            _artifact("impact", "impact_safety", _impact_payload()),
        ],
    )

    assert decision.approved is False
    assert any("写能力" in reason for reason in decision.reasons)


# 验证强制角色检查：required_roles 中角色缺少制品时拒绝完成。
def test_gate_rejects_missing_required_role():
    gate = CompletionGate(required_roles={"resource_planning"})
    decision = gate.evaluate(
        _incident(),
        _plan(),
        {"diagnose": "completed", "impact": "completed"},
        [
            _artifact("diagnose", "diagnosis", _diagnosis_payload()),
            _artifact("impact", "impact_safety", _impact_payload()),
        ],
    )

    assert decision.approved is False
    assert any("强制制品角色" in reason for reason in decision.reasons)


# 验证 WritePolicy 拒绝携带写能力的计划。
def test_write_policy_rejects_write_plan():
    plan = _plan()
    plan.tasks[1].allowed_capabilities = {"java.dispatch.write"}

    with pytest.raises(ValueError, match="PLAN_WRITE_POLICY_VIOLATION"):
        WritePolicy.assert_read_only(plan)


# 验证 WritePolicy 接受纯只读计划。
def test_write_policy_accepts_read_only_plan():
    WritePolicy.assert_read_only(_plan())


# 验证派单建议生成：只含只读结论、证据引用与审批要求。
def test_build_dispatch_proposal_is_read_only():
    proposal = build_dispatch_proposal(
        _incident(dispatch_target="WO-1"),
        _plan(version=2),
        [
            _artifact("diagnose", "diagnosis", _diagnosis_payload()),
            _artifact("impact", "impact_safety", _impact_payload(risk="critical")),
        ],
    )

    assert proposal.work_order_id == "WO-1"
    assert proposal.plan_version == 2
    assert proposal.requires_approval is True
    assert proposal.evidence_refs == ["chunk-1"]
    assert proposal.risk_level == "critical"
    assert "电源模块故障" in proposal.proposed_action
    assert WritePolicy.validate_proposal(proposal) == []


# 验证派单建议校验：内嵌写命令或缺少证据/审批时列出违规。
def test_write_policy_flags_bad_proposal():
    bad = DispatchProposal(
        proposal_id="p1",
        incident_id="i1",
        plan_id="plan-1",
        plan_version=1,
        work_order_id="",
        proposed_action="update work order and create assignment",
        reason="x",
        requires_approval=False,
    )

    violations = WritePolicy.validate_proposal(bad)

    assert "proposal 内嵌写命令" in violations
    assert "proposal 缺少证据支撑" in violations
    assert "proposal 必须要求人工审批" in violations
    assert "proposal 缺少目标工单" in violations
