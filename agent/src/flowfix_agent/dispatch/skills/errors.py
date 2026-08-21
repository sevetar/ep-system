from flowfix_agent.dispatch.domain.errors import DispatchError


# Skill Manifest 格式错误或违反安全约束时抛出的异常。
class DispatchSkillValidationError(DispatchError):
    """Skill Manifest 格式错误或违反安全约束。"""


# 指定或当前激活的 Skill 不存在时抛出的异常。
class DispatchSkillNotFoundError(DispatchError):
    """指定或当前激活的 Skill 不存在。"""


# Skill 没有可恢复的历史激活版本时抛出的异常。
class DispatchSkillRollbackError(DispatchError):
    """Skill 没有可以恢复的历史激活版本。"""
