import pytest

from flowfix_agent.dispatch.adapters.proposal_bridge import (
    ProposalDispatchBridge,
    ProposalTransferError,
)
from flowfix_agent.dispatch.runtime.models import DispatchRuntimeInput, RequestContext
from flowfix_agent.planning.models import DispatchProposal


def _proposal(**overrides) -> DispatchProposal:
    values = {
        "proposal_id": "proposal-i1-v1",
        "incident_id": "i1",
        "plan_id": "plan-1",
        "plan_version": 1,
        "work_order_id": "WO-1",
        "proposed_action": "依据调查结果更换电源模块",
        "reason": "完成门禁通过，生成派单建议。",
        "risk_level": "critical",
        "evidence_refs": ["chunk-1"],
        "requires_approval": True,
    }
    values.update(overrides)
    return DispatchProposal(**values)


def _bridge() -> ProposalDispatchBridge:
    # 仅验证边界组装与校验逻辑，不真正启动派单运行时。
    return ProposalDispatchBridge(runtime=object(), timeout_seconds=60.0)  # type: ignore[arg-type]


# 验证合规建议组装出带强制审批、血缘一致的派单运行时输入。
def test_bridge_builds_compliant_input():
    runtime_input = _bridge().to_runtime_input(_proposal(), tenant_id="tenant-1")

    assert isinstance(runtime_input, DispatchRuntimeInput)
    assert runtime_input.requires_approval is True
    assert runtime_input.work_order_id == "WO-1"
    assert runtime_input.request.dispatch_id == "proposal-i1-v1"
    assert runtime_input.request.event_id == "proposal-i1-v1"
    assert runtime_input.request.tenant_id == "tenant-1"
    assert runtime_input.context.event_id == "proposal-i1-v1"
    assert runtime_input.context.tenant_id == "tenant-1"
    assert {"dispatch:read", "dispatch:write", "dispatch:audit"} <= set(
        runtime_input.context.permissions
    )


# 验证内嵌写命令的建议被拒绝转交（WritePolicy 防线前置）。
def test_bridge_rejects_embedded_write_command():
    proposal = _proposal(proposed_action="update work order and create assignment")

    with pytest.raises(ProposalTransferError, match="只读校验"):
        _bridge().to_runtime_input(proposal, tenant_id="tenant-1")


# 验证缺少证据支撑的建议被拒绝转交。
def test_bridge_rejects_missing_evidence():
    proposal = _proposal(evidence_refs=[])

    with pytest.raises(ProposalTransferError, match="只读校验"):
        _bridge().to_runtime_input(proposal, tenant_id="tenant-1")


# 验证 requires_approval 被篡改为 False 时强制拒绝。
def test_bridge_rejects_without_approval():
    proposal = _proposal(requires_approval=False)

    with pytest.raises(ProposalTransferError, match="人工审批"):
        _bridge().to_runtime_input(proposal, tenant_id="tenant-1")


# 验证缺少目标工单的建议被拒绝转交。
def test_bridge_rejects_missing_work_order():
    proposal = _proposal(work_order_id="")

    with pytest.raises(ProposalTransferError, match="只读校验"):
        _bridge().to_runtime_input(proposal, tenant_id="tenant-1")


# 验证缺少租户上下文时拒绝转交。
def test_bridge_rejects_empty_tenant():
    with pytest.raises(ProposalTransferError, match="租户"):
        _bridge().to_runtime_input(_proposal(), tenant_id="")


# 验证调用方上下文的血缘不匹配时拒绝转交（事件与租户都前置校验）。
def test_bridge_rejects_mismatched_context():
    context = RequestContext(
        trace_id="t",
        tenant_id="tenant-1",
        event_id="wrong-event",
        permissions=[],
        deadline="2026-08-06T00:00:00Z",
    )

    with pytest.raises(ProposalTransferError, match="event_id"):
        _bridge().to_runtime_input(_proposal(), tenant_id="tenant-1", context=context)


# 验证调用方提供的合规上下文被原样使用，不重复构造。
def test_bridge_accepts_caller_context():
    context = RequestContext(
        trace_id="caller-trace",
        tenant_id="tenant-1",
        event_id="proposal-i1-v1",
        permissions=["dispatch:read", "dispatch:write", "dispatch:audit"],
        deadline="2026-08-06T00:00:00Z",
    )

    runtime_input = _bridge().to_runtime_input(
        _proposal(), tenant_id="tenant-1", context=context
    )

    assert runtime_input.context.trace_id == "caller-trace"
