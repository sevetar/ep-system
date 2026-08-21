from flowfix_agent.core.errors import FlowFixError


# 调度领域异常的统一基类。
class DispatchError(FlowFixError):
    """派单离线决策的基类错误。"""


# 状态机发生非法流转时抛出的异常。
class InvalidStateTransitionError(DispatchError):
    """派单状态流转违反显式状态机时抛出的异常。"""

