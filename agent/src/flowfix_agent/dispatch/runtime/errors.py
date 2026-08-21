from flowfix_agent.core.errors import FlowFixError


# M4 派单运行时异常的统一基类。
class DispatchRuntimeError(FlowFixError):
    """M4 运行时错误基类。"""


# 工具不满足系统、Skill 或请求权限约束时抛出的异常。
class ToolAccessDeniedError(DispatchRuntimeError):
    """系统、Skill 或请求上下文不允许调用 Tool。"""


# 工具输入违反租户、事件、幂等或版本合同时抛出的异常。
class ToolContractError(DispatchRuntimeError):
    """Tool 输入不满足租户、幂等或版本合同。"""


# 请求截止时间已到或单次工具调用超时时抛出的异常。
class ToolDeadlineExceededError(DispatchRuntimeError):
    """请求截止时间已到或单次 Tool 调用超时。"""


# 单次运行超过工具调用预算时抛出的限流异常。
class ToolRateLimitError(DispatchRuntimeError):
    """单次运行的 Tool 调用次数超过预算。"""


# 工具连续失败达到阈值并进入熔断状态时抛出的异常。
class ToolCircuitOpenError(DispatchRuntimeError):
    """Tool 连续失败后熔断。"""


# 人工审批结果无法安全映射到冻结候选集时抛出的异常。
class ApprovalValidationError(DispatchRuntimeError):
    """人工审批结果不能安全映射到当前候选集。"""
