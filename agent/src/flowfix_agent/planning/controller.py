from __future__ import annotations

from flowfix_agent.memory.ports import TaskArtifactStorePort
from flowfix_agent.memory.task_artifact import TaskArtifactRecord
from flowfix_agent.planning.models import CommittedPlan, IncidentContext, PlanDraft, PlanPatch
from flowfix_agent.planning.validation import PlanValidator


# 计划控制器：校验并版本化提交初始计划与 Replan 补丁。
class PlanController:
    # 绑定 Task/Artifact 存储与计划校验器。
    def __init__(self, store: TaskArtifactStorePort, validator: PlanValidator) -> None:
        self.store = store
        self.validator = validator

    # 校验并提交初始计划，返回带版本号的已提交计划。
    def commit_initial(self, incident: IncidentContext, draft: PlanDraft) -> CommittedPlan:
        self.validator.validate(incident, draft)
        saved = self.store.put(
            TaskArtifactRecord(
                tenant_id=incident.tenant_id,
                thread_id=incident.thread_id,
                plan_id=draft.plan_id,
                entity_id=draft.plan_id,
                kind="plan",
                payload=draft.model_dump(mode="json"),
                source="planner",
                trace_id=incident.trace_id,
            ),
            expected_version=0,
        )
        return CommittedPlan(**draft.model_dump(), version=saved.version)

    # 应用 Replan 补丁：版本一致时取消旧任务并加入新任务后重新提交。
    def apply_patch(
        self, incident: IncidentContext, plan: CommittedPlan, patch: PlanPatch
    ) -> CommittedPlan:
        if patch.expected_plan_version != plan.version:
            raise ValueError("PLAN_VERSION_CONFLICT")
        cancelled = set(patch.cancel_task_ids)
        draft = PlanDraft(
            plan_id=plan.plan_id,
            tasks=[task for task in plan.tasks if task.task_id not in cancelled]
            + patch.add_tasks,
        )
        self.validator.validate(incident, draft)
        saved = self.store.put(
            TaskArtifactRecord(
                tenant_id=incident.tenant_id,
                thread_id=incident.thread_id,
                plan_id=plan.plan_id,
                entity_id=plan.plan_id,
                kind="plan",
                payload=draft.model_dump(mode="json"),
                source="replanner",
                trace_id=incident.trace_id,
                version=plan.version,
            ),
            expected_version=plan.version,
        )
        return CommittedPlan(**draft.model_dump(), version=saved.version)
