from __future__ import annotations

from flowfix_agent.dispatch.domain.models import CandidateScore, WorkerSnapshot, WorkOrderSnapshot
from flowfix_agent.dispatch.skills.manifest import DispatchSkill, TieBreakPolicy


# 计算候选工作人员的加权得分并生成稳定排名。
def score_candidates(
    order: WorkOrderSnapshot,
    workers: list[WorkerSnapshot],
    skill: DispatchSkill,
) -> list[CandidateScore]:
    """计算归一化分数，并用显式规则保证同输入得到同一排序。"""
    weighted: list[tuple[WorkerSnapshot, float, dict[str, float]]] = []
    weights = skill.scoring_weights
    maximum_distance = skill.eligibility_rules.max_distance_km

    for worker in workers:
        components = {
            "load": max(0.0, 1.0 - worker.load_ratio),
            "skill": sum(worker.skills[name] for name in order.required_skills)
            / len(order.required_skills),
        }
        active_weights = {"load": weights.load, "skill": weights.skill}
        if worker.distance_km is not None:
            components["distance"] = max(
                0.0, 1.0 - worker.distance_km / maximum_distance
            )
            active_weights["distance"] = weights.distance
        if worker.sla_readiness is not None:
            components["sla"] = worker.sla_readiness
            active_weights["sla"] = weights.sla
        weight_total = sum(active_weights.values())
        total = sum(
            components[name] * weight / weight_total
            for name, weight in active_weights.items()
        )
        weighted.append((worker, round(total, 8), components))

    # 根据策略构造稳定排序键，在同分时应用指定规则。
    def tie_key(item: tuple[WorkerSnapshot, float, dict[str, float]]) -> tuple:
        worker, total, _ = item
        prefix: tuple[float, ...]
        if skill.tie_break_policy == TieBreakPolicy.LOWEST_LOAD_THEN_WORKER_ID:
            prefix = (worker.load_ratio,)
        elif skill.tie_break_policy == TieBreakPolicy.NEAREST_THEN_WORKER_ID:
            prefix = (
                worker.distance_km
                if worker.distance_km is not None
                else float("inf"),
            )
        else:
            prefix = ()
        return (-total, *prefix, worker.worker_id)

    ranked = sorted(weighted, key=tie_key)
    return [
        CandidateScore(
            worker_id=worker.worker_id,
            total_score=total,
            components={key: round(value, 8) for key, value in components.items()},
            reasons=[
                f"total_score:{total:.4f}",
                f"tie_break:{skill.tie_break_policy}",
            ],
            rank=rank,
        )
        for rank, (worker, total, components) in enumerate(ranked, start=1)
    ]
