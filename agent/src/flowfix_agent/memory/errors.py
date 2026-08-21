from flowfix_agent.core.errors import FlowFixError


# 会话或 Task/Artifact 写入时版本冲突/已存在抛出的异常。
class MemoryConflictError(FlowFixError):
    pass
