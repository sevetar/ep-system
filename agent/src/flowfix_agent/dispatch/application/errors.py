from flowfix_agent.dispatch.domain.errors import DispatchError


# 同一事件标识对应不同不可变输入时抛出的幂等冲突异常。
class IdempotencyConflictError(DispatchError):
    """同一事件标识被用于不同的不可变派单输入。"""
