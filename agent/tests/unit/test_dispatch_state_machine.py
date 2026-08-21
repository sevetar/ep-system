from datetime import UTC, datetime

import pytest

from flowfix_agent.dispatch.domain.errors import InvalidStateTransitionError
from flowfix_agent.dispatch.domain.models import DispatchState, DispatchStatus
from flowfix_agent.dispatch.domain.state_machine import transition


# 构造处于接收状态的最小派单状态。
def make_state() -> DispatchState:
    return DispatchState(
        dispatch_id="dispatch-1",
        event_id="event-1",
        tenant_id="tenant-1",
        skill_id="balanced",
        skill_version="1.0.0",
        skill_content_hash="abc",
        input_fingerprint="input",
    )


# 验证合法流转会更新状态并保留完整审计历史。
def test_valid_transition_keeps_audit_history() -> None:
    validated = transition(make_state(), DispatchStatus.VALIDATED, "valid")
    decided = transition(validated, DispatchStatus.DECIDED, "selected")

    assert decided.status == DispatchStatus.DECIDED
    assert [item.target for item in decided.transitions] == [
        DispatchStatus.VALIDATED,
        DispatchStatus.DECIDED,
    ]


# 验证未声明流转和终态继续流转都会失败关闭。
@pytest.mark.parametrize(
    ("source", "target"),
    [
        (DispatchStatus.RECEIVED, DispatchStatus.DECIDED),
        (DispatchStatus.DECIDED, DispatchStatus.VALIDATED),
        (DispatchStatus.MANUAL, DispatchStatus.DECIDED),
    ],
)
def test_invalid_and_terminal_transitions_fail_closed(source, target) -> None:
    state = make_state().model_copy(update={"status": source})
    with pytest.raises(InvalidStateTransitionError):
        transition(state, target, datetime.now(UTC).isoformat())
