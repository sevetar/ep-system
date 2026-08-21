from __future__ import annotations

from flowfix_agent.planning.models import (
    CommittedPlan,
    PlanPatch,
    ReplanTrigger,
    TaskSpec,
)


# 按结构化标记从制品中识别三类内容触发的重规划信号。
class RuleBasedReplanDetector:
    """优先级：resource_unavailable > artifact_conflict > new_evidence。

    只检查当前计划版本产生的制品，避免把已重规划任务留下的旧标记再次误判。
    """

    # 初始化启用的触发器集合，None 表示全部启用。
    def __init__(self, enabled: set[str] | None = None) -> None:
        # enabled 允许在测试中只启用部分触发器，默认全部启用。
        self.enabled = enabled or {
            "new_evidence",
            "artifact_conflict",
            "resource_unavailable",
        }

    # 扫描当前版本制品载荷，命中任一重规划信号即返回对应 ReplanTrigger，否则返回 None。
    #
    # 三种信号按优先级依次检查：resource_unavailable > artifact_conflict > new_evidence。
    # 调用方（planning/runtime.py 的 _supervise）在任务全部成功完成后仍会调用本方法，
    # 用于发现"执行成功但计划内容有问题"的内容触发场景：
    #   - resource_unavailable：资源规划确认关键资源不可用（primary_available=False），
    #     需要重新规划替代方案；
    #   - artifact_conflict：诊断结论与影响/安全评估结论互相冲突（conflict 非空）；
    #   - new_evidence：诊断过程中发现新证据推翻初始假设（hypothesis_revised 非空）。
    async def detect(self, incident, plan: CommittedPlan, statuses, artifacts):
        # 只检查当前计划版本产生的制品：
        # 重规划后旧版本任务留下的制品里可能仍带过期标记，若一并扫描会再次误判，
        # 导致同一信号被反复触发。plan_version 在 Worker 产出制品时写入。
        current = [item for item in artifacts if item.plan_version == plan.version]
        # 第一优先级：关键资源不可用。受 enabled 开关控制，可在测试中部分启用。
        if "resource_unavailable" in self.enabled:
            # 只在资源规划角色的制品里查找该信号，跳过其他角色制品。
            for artifact in current:
                if artifact.worker_id != "resource_planning":
                    continue
                # 载荷按角色分节存储，资源规划部分用 {} 兜底空制品，避免 .get 链抛错。
                resource_planning = artifact.payload.get("resource_planning") or {}
                # primary_available 明确为 False 才算不可用；为 None 或字段缺失时不命中，
                # 避免把"数据缺失"误当成"资源不可用"而触发无谓重规划。
                if resource_planning.get("primary_available") is False:
                    # 命中即返回：携带触发类型、可读原因与需取消的任务 ID。
                    # reason 优先用制品里记录的 missing_info，缺失时给兜底文案"无可用备件"。
                    return ReplanTrigger(
                        trigger="resource_unavailable",
                        reason=(
                            "关键资源不可用，需重新规划替代方案："
                            f"{resource_planning.get('missing_info') or '无可用备件'}"
                        ),
                        cancel_task_ids=[artifact.task_id],
                    )
        # 第二、三优先级：诊断制品里的冲突与新证据。
        for artifact in current:
            if artifact.worker_id != "diagnosis":
                continue
            diagnosis = artifact.payload.get("diagnosis") or {}
            # 冲突信号：diagnosis.conflict 非空表示诊断结论与影响/安全评估结论冲突，
            # 需要重跑诊断任务核实。该信号同样受 enabled 开关控制。
            if "artifact_conflict" in self.enabled and diagnosis.get("conflict"):
                return ReplanTrigger(
                    trigger="artifact_conflict",
                    reason=f"诊断结论与影响评估结论冲突：{diagnosis['conflict']}",
                    cancel_task_ids=[artifact.task_id],
                )
            # 新证据信号：hypothesis_revised 非空表示诊断中新证据推翻了初始假设，
            # 计划基于旧假设展开，需要重新诊断。该信号同样受 enabled 开关控制。
            if "new_evidence" in self.enabled and diagnosis.get("hypothesis_revised"):
                return ReplanTrigger(
                    trigger="new_evidence",
                    reason=f"新证据推翻初始假设：{diagnosis['hypothesis_revised']}",
                    cancel_task_ids=[artifact.task_id],
                )
        # 全部制品均未命中任何信号：无需重规划，返回 None 让监督节点走正常收尾。
        return None


# 把内容触发或失败任务转换为版本一致的 PlanPatch 的确定性重规划器。
class RuleBasedReplanner:
    """内容触发时取消受影响任务并以「原ID-revised」新增复查任务；
    失败任务时取消失败任务并新增 recovery 任务。被取消任务的下游任务一并取消，
    避免悬空依赖导致补丁校验失败。全程不引入写能力。"""

    # 初始化触发器到执行角色的映射，默认映射三类触发器到诊断/资源规划角色。
    def __init__(self, role_mapping: dict[str, str] | None = None) -> None:
        # 触发器类型 → 重新执行任务需要的 Worker 角色。
        self.role_mapping = role_mapping or {
            "new_evidence": "diagnosis",
            "artifact_conflict": "diagnosis",
            "resource_unavailable": "resource_planning",
        }

    # 依据触发器或失败任务生成补丁，expected_plan_version 必须等于当前版本。
    async def replan(
        self,
        incident,
        plan: CommittedPlan,
        failed_task_ids: list[str],
        *,
        trigger: ReplanTrigger | None = None,
    ) -> PlanPatch:
        if trigger is not None:
            return self._patch_for_trigger(plan, trigger)
        return self._patch_for_failed(plan, failed_task_ids)

    # 为内容触发生成补丁：取消标记任务及其下游，新增带新 ID 的复查任务并保留原依赖。
    def _patch_for_trigger(
        self, plan: CommittedPlan, trigger: ReplanTrigger
    ) -> PlanPatch:
        cancelled = self._downstream_closure(plan, set(trigger.cancel_task_ids))
        by_id = {task.task_id: task for task in plan.tasks}
        role = self.role_mapping[trigger.trigger]
        add_tasks: list[TaskSpec] = []
        for task_id in sorted(trigger.cancel_task_ids):
            original = by_id.get(task_id)
            deps = [
                dependency
                for dependency in (original.dependencies if original else [])
                if dependency not in cancelled
            ]
            add_tasks.append(
                TaskSpec(
                    task_id=f"{task_id}-revised",
                    description=f"依据重规划信号重新评估：{trigger.reason}",
                    required_role=role,
                    dependencies=deps,
                    allowed_capabilities=(
                        set(original.allowed_capabilities) if original else set()
                    ),
                )
            )
        return PlanPatch(
            add_tasks=add_tasks,
            cancel_task_ids=sorted(cancelled),
            expected_plan_version=plan.version,
        )

    # 为失败任务生成兜底补丁：取消失败任务及其下游，新增恢复同角色工作的 recovery 任务。
    @staticmethod
    def _patch_for_failed(plan: CommittedPlan, failed_task_ids: list[str]) -> PlanPatch:
        cancelled = RuleBasedReplanner._downstream_closure(plan, set(failed_task_ids))
        by_id = {task.task_id: task for task in plan.tasks}
        roles = {by_id[task_id].required_role for task_id in failed_task_ids if task_id in by_id}
        # 多个不同角色的任务同时失败时无法用单任务恢复，回退到诊断角色。
        recovery_role = next(iter(roles)) if len(roles) == 1 else "diagnosis"
        return PlanPatch(
            add_tasks=[
                TaskSpec(
                    task_id="recovery",
                    description="收集替代证据并恢复计划执行",
                    required_role=recovery_role,
                )
            ],
            cancel_task_ids=sorted(cancelled),
            expected_plan_version=plan.version,
        )

    # 计算被取消任务的传递下游闭包：无法获得依赖制品的任务一并取消。
    @staticmethod
    def _downstream_closure(plan: CommittedPlan, cancelled: set[str]) -> set[str]:
        result = set(cancelled)
        changed = True
        while changed:
            changed = False
            for task in plan.tasks:
                if task.task_id in result:
                    continue
                if set(task.dependencies) & result:
                    result.add(task.task_id)
                    changed = True
        return result
