from __future__ import annotations

from flowfix_agent.dispatch.domain.errors import InvalidStateTransitionError
from flowfix_agent.dispatch.domain.models import DispatchState, DispatchStatus, StateTransition

TERMINAL_STATUSES = {
    DispatchStatus.DECIDED,
    DispatchStatus.MANUAL,
    DispatchStatus.REJECTED,
    DispatchStatus.FAILED,
}

ALLOWED_TRANSITIONS = {
    DispatchStatus.RECEIVED: {
        DispatchStatus.VALIDATED,
        DispatchStatus.REJECTED,
        DispatchStatus.FAILED,
    },
    DispatchStatus.VALIDATED: {
        DispatchStatus.DECIDED,
        DispatchStatus.MANUAL,
        DispatchStatus.REJECTED,
        DispatchStatus.FAILED,
    },
}


# 校验并执行一次调度状态流转，同时追加流转记录。
def transition(
    state: DispatchState,
    target: DispatchStatus,
    reason: str,
) -> DispatchState:
    allowed = ALLOWED_TRANSITIONS.get(state.status, set())
    if target not in allowed:
        raise InvalidStateTransitionError(
            f"Invalid dispatch transition: {state.status} -> {target}"
        )
    return state.model_copy(
        update={
            "status": target,
            "transitions": [
                *state.transitions,
                StateTransition(source=state.status, target=target, reason=reason),
            ],
        },
        deep=True,
    )
