from __future__ import annotations

from flowfix_agent.core.errors import FlowFixError
from flowfix_agent.planning.models import IncidentContext, PlanDraft


# 计划校验失败时抛出的异常。
class PlanValidationError(FlowFixError):
    pass


# 计划校验器：拒绝空计划、超预算、重复 ID、悬空依赖、写能力（assignment.create）、
# 角色缺失与环形 DAG。
class PlanValidator:
    # 校验计划草稿，不满足任何安全约束即抛错。
    def validate(self, incident: IncidentContext, draft: PlanDraft) -> None:
        if not draft.tasks:
            raise PlanValidationError("PLAN_EMPTY")
        if len(draft.tasks) > incident.max_tasks:
            raise PlanValidationError("PLAN_TASK_BUDGET_EXCEEDED")
        ids = [task.task_id for task in draft.tasks]
        if len(ids) != len(set(ids)):
            raise PlanValidationError("PLAN_DUPLICATE_TASK_ID")
        known = set(ids)
        for task in draft.tasks:
            if not task.required_role:
                raise PlanValidationError("PLAN_ROLE_REQUIRED")
            if not set(task.dependencies) <= known:
                raise PlanValidationError("PLAN_DANGLING_DEPENDENCY")
            if any(capability == "assignment.create" for capability in task.allowed_capabilities):
                raise PlanValidationError("PLAN_WRITE_CAPABILITY_DENIED")
        self._assert_acyclic(draft)

    # 通过拓扑剔除检测 DAG 是否存在环。
    @staticmethod
    def _assert_acyclic(draft: PlanDraft) -> None:
        dependencies = {task.task_id: set(task.dependencies) for task in draft.tasks}
        remaining = set(dependencies)
        while remaining:
            ready = {task for task in remaining if not (dependencies[task] & remaining)}
            if not ready:
                raise PlanValidationError("PLAN_CYCLE")
            remaining -= ready
