from flowfix_agent.core.errors import FlowFixError


# 工具平台基础异常，继承领域 FlowFixError。
class ToolPlatformError(FlowFixError):
    pass


# 能力未注册时抛出。
class CapabilityNotFoundError(ToolPlatformError):
    pass


# 调用未获授权或超出调用预算时抛出。
class ToolAuthorizationError(ToolPlatformError):
    pass


# 输入参数校验失败时抛出。
class ToolInputError(ToolPlatformError):
    pass


# Provider 执行失败、超时或输出校验失败时抛出。
class ToolExecutionError(ToolPlatformError):
    pass
