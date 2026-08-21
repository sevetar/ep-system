from __future__ import annotations

from dataclasses import dataclass

from flowfix_agent.dispatch.domain.models import (
    CandidateExclusion,
    DispatchRequest,
    WorkerSnapshot,
    WorkOrderSnapshot,
    WorkOrderStatus,
)
from flowfix_agent.dispatch.skills.manifest import DispatchSkill


# 汇总通过资格校验和被排除的工作人员。
@dataclass(frozen=True)
class EligibilityResult:
    eligible: list[WorkerSnapshot]
    exclusions: list[CandidateExclusion]


# 校验不可被策略放宽的工单安全条件。
def validate_work_order(
    request: DispatchRequest,
    order: WorkOrderSnapshot,
) -> list[str]:
    """返回不可由 Skill 关闭的工单安全门禁错误。"""
    errors: list[str] = []
    if request.tenant_id != order.tenant_id:
        errors.append("request_order_tenant_mismatch")
    if order.status != WorkOrderStatus.PENDING_DISPATCH:
        errors.append(f"work_order_status_not_dispatchable:{order.status}")
    if order.assigned_worker_id is not None:
        errors.append("work_order_already_assigned")
    return errors


# 根据硬性门禁和当前策略筛选可参与评分的工作人员。
def filter_workers(
    order: WorkOrderSnapshot,
    workers: list[WorkerSnapshot],
    skill: DispatchSkill,
) -> EligibilityResult:
    """先执行硬门禁，再执行 Skill 可调但只能收紧的资格条件。"""
    # 结果容器：合格候选与排除记录（带原因，供审计与前端展示）。
    eligible: list[WorkerSnapshot] = []
    exclusions: list[CandidateExclusion] = []
    # 取出 Skill 声明的可调资格规则（区域/距离/负载率等配置来源）。
    rules = skill.eligibility_rules

    # 按 worker_id 排序遍历，保证同一输入产出确定性结果（幂等、可测试）。
    for worker in sorted(workers, key=lambda item: item.worker_id):
        # 每个工人独立累积所有不合格原因。
        reasons: list[str] = []
        # 硬门禁一：租户必须与工单一致，跨租户工人直接排除。
        if worker.tenant_id != order.tenant_id:
            reasons.append("tenant_mismatch")
        # 硬门禁二：工人当前不可用则排除。
        if not worker.available:
            reasons.append("worker_unavailable")
        # 硬门禁三：不在当班时段则排除。
        if not worker.shift_active:
            reasons.append("shift_inactive")
        # 硬门禁四：负载已达或超过容量上限则排除（满载不接新单）。
        if worker.current_load >= worker.capacity:
            reasons.append("capacity_exhausted")

        # 硬门禁五：工单必需技能与工人技能的差集；去重后排序保证原因顺序稳定。
        missing_skills = sorted(set(order.required_skills) - set(worker.skills))
        if missing_skills:
            reasons.append(f"missing_skills:{','.join(missing_skills)}")

        # Skill 可调条件（只能收紧，不能放宽）：
        # 区域匹配仅在 Skill 要求时才检查；距离未知（None）时不据此误杀。
        if rules.require_region_match and worker.region != order.region:
            reasons.append("region_mismatch")
        if worker.distance_km is not None and worker.distance_km > rules.max_distance_km:
            reasons.append("distance_exceeded")
        if worker.load_ratio > rules.max_load_ratio:
            reasons.append("load_ratio_exceeded")

        # 有任何不合格原因 → 记入排除列表（保留完整原因）；否则进入合格候选。
        if reasons:
            exclusions.append(
                CandidateExclusion(worker_id=worker.worker_id, reasons=reasons)
            )
        else:
            eligible.append(worker)
    # 返回聚合结果：合格候选 + 排除记录。
    return EligibilityResult(eligible=eligible, exclusions=exclusions)
