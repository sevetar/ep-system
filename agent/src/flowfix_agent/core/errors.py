# 定义 FlowFix 业务异常的统一基类。
class FlowFixError(Exception):
    pass


# 表示应用配置缺失或格式无效。
class ConfigurationError(FlowFixError):
    pass


# 表示知识源无法读取或未通过路径与内容校验。
class KnowledgeSourceError(FlowFixError):
    pass


# 表示当前请求依赖的外部服务不可用。
class DependencyUnavailableError(FlowFixError):
    pass


# 表示生成答案缺少有效证据引用或引用编号非法。
class CitationValidationError(FlowFixError):
    pass


# 表示业务层检测到 Principal、tenant 或资源归属不一致。
class RequestAuthorizationError(FlowFixError):
    pass
