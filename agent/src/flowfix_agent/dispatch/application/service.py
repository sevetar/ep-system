from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

from flowfix_agent.dispatch.application.errors import IdempotencyConflictError
from flowfix_agent.dispatch.application.ports import (
    DispatchDecisionRepositoryPort,
    DispatchSkillRegistryPort,
    DispatchTracePort,
)
from flowfix_agent.dispatch.application.rules import filter_workers, validate_work_order
from flowfix_agent.dispatch.application.scoring import score_candidates
from flowfix_agent.dispatch.domain.models import (
    DispatchDecision,
    DispatchOutcome,
    DispatchRequest,
    DispatchState,
    DispatchStatus,
    RiskLevel,
    WorkerSnapshot,
    WorkOrderSnapshot,
)
from flowfix_agent.dispatch.domain.state_machine import transition
from flowfix_agent.dispatch.skills.manifest import DispatchSkill


# 保存已冻结输入、策略和初始状态，供后续稳定决策使用。
@dataclass(frozen=True)
class PreparedDispatch:
    request: DispatchRequest
    order: WorkOrderSnapshot
    workers: list[WorkerSnapshot]
    skill: DispatchSkill
    state: DispatchState


# 编排输入冻结、资格筛选、评分、决策保存与追踪。
class DispatchDecisionService:
    """确定性派单决策内核：只产生决策，不直接写外部业务状态。"""

    # 注入策略注册表、决策仓库和可选追踪端口。
    def __init__(
        self,
        registry: DispatchSkillRegistryPort,
        repository: DispatchDecisionRepositoryPort,
        trace: DispatchTracePort | None = None,
    ) -> None:
        self.registry = registry
        self.repository = repository
        self.trace = trace

    # 深拷贝输入并冻结显式传入或当前激活的策略，构造可重复执行的上下文。
    def prepare(
        self,
        request: DispatchRequest,
        order: WorkOrderSnapshot,
        workers: list[WorkerSnapshot],
        skill: DispatchSkill | None = None,
    ) -> PreparedDispatch:
        """在任务开始时深拷贝输入，并冻结显式传入或当前 active Skill。"""
        frozen_request = request.model_copy(deep=True)
        frozen_order = order.model_copy(deep=True)
        frozen_workers = sorted(
            (worker.model_copy(deep=True) for worker in workers),
            key=lambda worker: worker.worker_id,
        )
        frozen_skill = (skill or self.registry.get_active()).model_copy(deep=True)
        fingerprint = _fingerprint(
            {
                "request": frozen_request,
                "order": frozen_order,
                "workers": frozen_workers,
                "skill_id": frozen_skill.skill_id,
                "skill_version": frozen_skill.skill_version,
                "skill_content_hash": frozen_skill.content_hash,
            }
        )
        state = DispatchState(
            dispatch_id=frozen_request.dispatch_id,
            event_id=frozen_request.event_id,
            tenant_id=frozen_request.tenant_id,
            skill_id=frozen_skill.skill_id,
            skill_version=frozen_skill.skill_version,
            skill_content_hash=frozen_skill.content_hash,
            input_fingerprint=fingerprint,
        )
        return PreparedDispatch(
            request=frozen_request,
            order=frozen_order,
            workers=frozen_workers,
            skill=frozen_skill,
            state=state,
        )

    # 从原始快照准备上下文并执行完整调度决策。
    async def decide(
        self,
        request: DispatchRequest,
        order: WorkOrderSnapshot,
        workers: list[WorkerSnapshot],
    ) -> DispatchDecision:
        return await self.decide_prepared(self.prepare(request, order, workers))

    # 对已冻结的上下文执行校验、筛选、评分和风险分流。
    async def decide_prepared(self, prepared: PreparedDispatch) -> DispatchDecision:
        # 幂等入口：按事件 ID 查询该事件是否已有决策记录
        existing = await self.repository.get_by_event(prepared.request.event_id)
        # 已有决策：校验指纹是否与本次输入一致
        if existing:
            # 一致则直接返回既有决策，不一致则抛幂等冲突，防止同一事件重复决策
            return _same_or_conflict(existing, prepared.state.input_fingerprint)

        # 取出冻结的初始派单状态
        state = prepared.state
        # 校验工单快照是否满足派单前提（状态、字段等）
        order_errors = validate_work_order(prepared.request, prepared.order)
        # 校验策略声明必填的快照字段是否齐全
        required_errors = _validate_required_fields(prepared)
        # 任一校验失败则整单拒绝
        if order_errors or required_errors:
            # 合并两类校验错误作为拒绝原因
            reasons = [*order_errors, *required_errors]
            # 状态流转为拒绝（request_rejected）
            state = transition(state, DispatchStatus.REJECTED, "request_rejected")
            # 构造高风险的拒绝决策
            decision = _build_decision(
                prepared, state, DispatchOutcome.REJECTED, RiskLevel.HIGH, reasons
            )
            # 幂等保存并上报追踪后返回
            return await self._save_and_trace(decision)

        # 校验通过，状态流转为已校验（request_validated）
        state = transition(state, DispatchStatus.VALIDATED, "request_validated")
        # 按策略筛选出合格工作人员与排除名单
        eligibility = filter_workers(prepared.order, prepared.workers, prepared.skill)
        # 把排除名单写入状态
        state = state.model_copy(update={"exclusions": eligibility.exclusions}, deep=True)
        # 无任何合格候选：转人工介入
        if not eligibility.eligible:
            # 状态流转为人工介入（no_eligible_candidates）
            state = transition(state, DispatchStatus.MANUAL, "no_eligible_candidates")
            # 构造高风险的人工介入决策
            decision = _build_decision(
                prepared,
                state,
                DispatchOutcome.MANUAL,
                RiskLevel.HIGH,
                ["no_eligible_candidates", "manual_review_required"],
            )
            # 幂等保存并上报追踪后返回
            return await self._save_and_trace(decision)

        # 对合格候选按策略评分排序
        candidates = score_candidates(
            prepared.order, eligibility.eligible, prepared.skill
        )
        # 取评分最高者作为自动派单首选
        top = candidates[0]
        # 计算最高分与第二名的分差（候选不足两个时视为分差足够大）
        margin = top.total_score - candidates[1].total_score if len(candidates) > 1 else 1.0
        # 读取策略声明的风险阈值
        thresholds = prepared.skill.risk_thresholds
        # 工单优先级是否被策略强制要求人工审批
        force_manual = prepared.order.priority in thresholds.force_manual_priorities
        # 最高分是否低于自动派单的最低得分阈值
        below_score = top.total_score < thresholds.minimum_auto_score
        # 最高分与第二名分差是否低于最小分差阈值
        below_margin = margin < thresholds.minimum_score_margin

        # 把评分候选与排除名单写入状态
        state = state.model_copy(
            update={"candidates": candidates, "exclusions": eligibility.exclusions},
            deep=True,
        )
        # 命中任一风险条件（强制人工/得分过低/分差过小）则转人工
        if force_manual or below_score or below_margin:
            # 初始化人工介入原因列表
            reasons = ["manual_review_required"]
            # 优先级强制人工：记录优先级
            if force_manual:
                reasons.append(f"priority_forces_manual:{prepared.order.priority}")
            # 得分低于阈值：记录实际得分
            if below_score:
                reasons.append(f"score_below_auto_threshold:{top.total_score:.4f}")
            # 分差过小：记录实际分差
            if below_margin:
                reasons.append(f"score_margin_too_small:{margin:.4f}")
            # 状态流转为人工介入（risk_threshold_triggered）
            state = transition(state, DispatchStatus.MANUAL, "risk_threshold_triggered")
            # 构造中等风险的人工介入决策
            decision = _build_decision(
                prepared, state, DispatchOutcome.MANUAL, RiskLevel.MEDIUM, reasons
            )
        # 未命中任何风险条件：自动派单
        else:
            # 记录选中的工作人员
            state = state.model_copy(update={"selected_worker_id": top.worker_id}, deep=True)
            # 状态流转为已决策（candidate_selected）
            state = transition(state, DispatchStatus.DECIDED, "candidate_selected")
            # 构造低风险的自动派单决策，记录选中原因与得分
            decision = _build_decision(
                prepared,
                state,
                DispatchOutcome.ASSIGN,
                RiskLevel.LOW,
                [
                    f"selected_highest_ranked_candidate:{top.worker_id}",
                    f"score:{top.total_score:.4f}",
                    f"score_margin:{margin:.4f}",
                ],
                selected_worker_id=top.worker_id,
            )
        # 幂等保存决策并上报追踪事件后返回
        return await self._save_and_trace(decision)

    # 幂等保存决策，并在配置追踪端口时发送决策事件。
    async def _save_and_trace(self, decision: DispatchDecision) -> DispatchDecision:
        saved = await self.repository.save_if_absent(decision)
        saved = _same_or_conflict(saved, decision.input_fingerprint)
        if self.trace:
            await self.trace.emit(
                "dispatch.decision",
                decision.dispatch_id,
                saved.model_dump(mode="json"),
            )
        return saved


# 根据准备上下文和最终状态构造带稳定指纹的决策对象。
def _build_decision(
    prepared: PreparedDispatch,
    state: DispatchState,
    outcome: DispatchOutcome,
    risk: RiskLevel,
    reasons: list[str],
    selected_worker_id: str | None = None,
) -> DispatchDecision:
    payload: dict[str, Any] = {
        "dispatch_id": prepared.request.dispatch_id,
        "event_id": prepared.request.event_id,
        "tenant_id": prepared.request.tenant_id,
        "work_order_id": prepared.order.work_order_id,
        "work_order_version": prepared.order.version,
        "status": state.status,
        "outcome": outcome,
        "selected_worker_id": selected_worker_id,
        "risk_level": risk,
        "skill_id": prepared.skill.skill_id,
        "skill_version": prepared.skill.skill_version,
        "skill_content_hash": prepared.skill.content_hash,
        "input_fingerprint": state.input_fingerprint,
        "candidates": state.candidates,
        "exclusions": state.exclusions,
        "reasons": reasons,
        "transitions": state.transitions,
        "decided_at": prepared.request.requested_at,
    }
    decision_fingerprint = _fingerprint(payload)
    return DispatchDecision(
        decision_id=f"decision-{decision_fingerprint[:20]}",
        decision_fingerprint=decision_fingerprint,
        **payload,
    )


# 检查同一事件的已有决策是否来自相同输入。
def _same_or_conflict(
    existing: DispatchDecision, input_fingerprint: str
) -> DispatchDecision:
    if existing.input_fingerprint != input_fingerprint:
        raise IdempotencyConflictError(
            f"event_id {existing.event_id} reused with different dispatch input"
        )
    return existing


# 检查当前策略声明的快照必填字段是否完整。
def _validate_required_fields(prepared: PreparedDispatch) -> list[str]:
    order = prepared.order.model_dump(mode="python")
    workers = [worker.model_dump(mode="python") for worker in prepared.workers]
    errors: list[str] = []
    for field in prepared.skill.required_snapshot_fields:
        scope, name = field.split(".", maxsplit=1)
        if scope == "work_order":
            values = [order.get(name)]
        else:
            values = [worker.get(name) for worker in workers]
        if not values or any(value is None or value == "" or value == [] for value in values):
            errors.append(f"required_snapshot_field_missing:{field}")
    return errors


# 将结构化输入稳定序列化后计算 SHA-256 指纹。
def _fingerprint(value: Any) -> str:
    # 将模型、时间和枚举转换为 JSON 可序列化值。
    def default(item: Any) -> Any:
        if hasattr(item, "model_dump"):
            return item.model_dump(mode="json")
        if isinstance(item, datetime):
            return item.isoformat()
        if isinstance(item, Enum):
            return item.value
        raise TypeError(f"Unsupported fingerprint value: {type(item)!r}")

    encoded = json.dumps(
        value,
        default=default,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
