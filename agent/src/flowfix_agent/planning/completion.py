from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, Field

from flowfix_agent.planning.models import (
    Artifact,
    CommittedPlan,
    DispatchProposal,
    IncidentContext,
    TaskStatus,
)

# 成功标准关键词到所需 Worker 角色的映射：某条标准命中关键词时要求对应角色制品。
CRITERION_ROLE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "diagnosis": ("根因", "原因", "诊断", "假设"),
    "impact_safety": ("影响", "风险", "安全", "范围"),
    "resource_planning": ("资源", "备件", "人员", "窗口", "方案"),
}


# 完成门禁的一次决策：是否批准完成及拒绝理由。
class CompletionDecision(BaseModel):
    approved: bool
    reasons: list[str] = Field(default_factory=list)


# 完成门禁：只有所有任务完成、强制制品齐全、无拒答、高风险被承认、成功标准被覆盖
# 且无写能力违规才批准完成。
class CompletionGate:
    """约束「不能提前完成」：
    - 任何任务未完成或缺少制品 → 拒绝；
    - 任一制品是证据不足的拒答 → 拒绝（转人工补证据）；
    - 高风险影响未附安全约束/必选校验 → 拒绝；
    - 成功标准未覆盖 → 拒绝；
    - 任务携带写能力 → 拒绝。
    """

    # 绑定可选的强制角色与成功标准关键词映射；required_roles 为空时仅按标准映射推断。
    def __init__(
        self,
        required_roles: set[str] | None = None,
        criterion_role_keywords: dict[str, tuple[str, ...]] | None = None,
    ) -> None:
        self.required_roles = required_roles or set()
        self.criterion_role_keywords = criterion_role_keywords or CRITERION_ROLE_KEYWORDS

    # 基于计划、状态表与制品计算完成决策。
    def evaluate(
        self,
        incident: IncidentContext,
        plan: CommittedPlan,
        statuses: dict[str, str],
        artifacts: Sequence[Artifact],
    ) -> CompletionDecision:
        # 累积所有不满足的门禁理由；为空则批准完成，非空则逐条拒绝。
        reasons: list[str] = []
        # 门禁一：收集所有状态不是 COMPLETED 的任务，任何未完成即拒绝。
        pending = [
            task_id
            for task_id, status in statuses.items()
            if status != TaskStatus.COMPLETED.value
        ]
        if pending:
            reasons.append(f"存在未完成任务：{pending}")
        # 门禁二：按任务 ID 索引制品，找出计划中存在但没有对应制品的任务。
        artifact_by_task = {artifact.task_id: artifact for artifact in artifacts}
        missing = [task.task_id for task in plan.tasks if task.task_id not in artifact_by_task]
        if missing:
            reasons.append(f"存在缺少制品的任务：{missing}")
        # 门禁三：按配置的强制角色校验，要求每个角色至少产出过一件制品。
        for role in sorted(self.required_roles):
            if not any(
                artifact.worker_id == role for artifact in artifacts
            ):
                reasons.append(f"缺少强制制品角色：{role}")
        # 门禁四：识别证据不足的拒答制品（各角色按自身结果结构判定），
        # 存在拒答说明结论无证据支撑，转人工补充而不是直接完成。
        refusals = [
            f"{artifact.task_id}({artifact.worker_id})：{reason}"
            for artifact in artifacts
            if (reason := _refusal_reason(artifact)) is not None
        ]
        if refusals:
            reasons.append(f"存在证据不足的拒答制品：{refusals}")
        # 门禁五：检查高风险影响是否未附安全约束/必选校验（未承认风险则阻断完成）。
        unacknowledged = [
            artifact.task_id
            for artifact in artifacts
            if _risk_not_acknowledged(artifact)
        ]
        if unacknowledged:
            reasons.append(f"高风险影响未被安全约束覆盖：{unacknowledged}")
        # 门禁六：逐条核对事故成功标准，未被任何非拒答制品覆盖的标准判为缺失。
        missing_criteria = [
            criterion
            for criterion in incident.success_criteria
            if not _criterion_covered(
                criterion, artifacts, self.criterion_role_keywords
            )
        ]
        if missing_criteria:
            reasons.append(f"成功标准未覆盖：{missing_criteria}")
        # 门禁七：调查链只读，计划中任何任务携带写能力都视为违规并拒绝完成。
        write_violations = [
            task.task_id
            for task in plan.tasks
            if _write_policy_violation(task.allowed_capabilities)
        ]
        if write_violations:
            reasons.append(f"任务携带写能力：{write_violations}")
        # 无任何拒绝理由才批准完成；否则携带全部理由返回，供监督节点转人工处理。
        return CompletionDecision(approved=not reasons, reasons=reasons)


# 写入策略：调查链只读，计划不得携带写能力，派单建议必须要求人工审批。
class WritePolicy:
    WRITE_CAPABILITIES = {
        "assignment.create",
        "work_order.update",
        "java.dispatch.write",
        "es.write",
    }

    # 校验计划中没有任何任务携带写能力，违反则抛 ValueError。
    @classmethod
    def assert_read_only(cls, plan: CommittedPlan) -> None:
        violations = [
            task.task_id
            for task in plan.tasks
            if _write_policy_violation(task.allowed_capabilities)
        ]
        if violations:
            raise ValueError(f"PLAN_WRITE_POLICY_VIOLATION: {violations}")

    # 校验派单建议合规：不内嵌写命令、有证据支撑、带目标工单且要求人工审批，返回违规列表。
    @classmethod
    def validate_proposal(cls, proposal: DispatchProposal) -> list[str]:
        violations: list[str] = []
        lowered = proposal.proposed_action.lower()
        if any(keyword in lowered for keyword in ("update", "create", "insert", "delete")):
            violations.append("proposal 内嵌写命令")
        if not proposal.evidence_refs:
            violations.append("proposal 缺少证据支撑")
        if not proposal.requires_approval:
            violations.append("proposal 必须要求人工审批")
        if not proposal.work_order_id:
            violations.append("proposal 缺少目标工单")
        return violations


# 生成调查完成后的派单建议：汇总各制品结论与引用，绝不直接写 Java/ES。
def build_dispatch_proposal(
    incident: IncidentContext, plan: CommittedPlan, artifacts: Sequence[Artifact]
) -> DispatchProposal:
    conclusions: list[str] = []
    risk_level: str | None = None
    for artifact in artifacts:
        diagnosis = artifact.payload.get("diagnosis") or {}
        impact = artifact.payload.get("impact_safety") or {}
        resource = artifact.payload.get("resource_planning") or {}
        if diagnosis.get("conclusion"):
            conclusions.append(str(diagnosis["conclusion"]))
        if impact.get("overall_risk_level"):
            risk_level = str(impact["overall_risk_level"])
        if resource.get("primary_available") is True:
            conclusions.append("关键资源可用，可安排处置")
        elif resource.get("alternatives"):
            conclusions.append("关键资源不可用，已提供替代方案")
    evidence_refs = sorted(
        {citation for artifact in artifacts for citation in artifact.evidence_refs}
    )
    return DispatchProposal(
        proposal_id=f"proposal-{incident.incident_id}-v{plan.version}",
        incident_id=incident.incident_id,
        plan_id=plan.plan_id,
        plan_version=plan.version,
        work_order_id=incident.dispatch_target or "",
        proposed_action=(
            "；".join(conclusions) if conclusions else "依据调查结果建议现场处置"
        ),
        reason=f"完成门禁通过，基于 {len(artifacts)} 个调查制品生成建议。",
        risk_level=risk_level,
        evidence_refs=evidence_refs,
        requires_approval=True,
    )


# 判断单个任务是否携带写能力。
def _write_policy_violation(allowed_capabilities) -> bool:
    return bool(set(allowed_capabilities) & WritePolicy.WRITE_CAPABILITIES)


# 判断制品是否为证据不足的拒答（各角色按自身结果结构识别）。
def _refusal_reason(artifact: Artifact) -> str | None:
    if artifact.worker_id == "diagnosis":
        diagnosis = artifact.payload.get("diagnosis") or {}
        if not diagnosis.get("hypotheses") and diagnosis.get("confidence", 1) == 0:
            return "诊断证据不足，拒绝给出根因假设"
    if artifact.worker_id == "impact_safety":
        impact = artifact.payload.get("impact_safety") or {}
        if impact.get("overall_risk_level") == "unknown":
            return "影响证据不足，无法评估风险"
    if artifact.worker_id == "resource_planning":
        resource = artifact.payload.get("resource_planning") or {}
        if resource.get("primary_available") is False and not resource.get("alternatives"):
            return "资源证据不足，无可用方案"
    return None


# 判断高风险影响是否未附安全约束或必选校验（未承认风险则阻断完成）。
def _risk_not_acknowledged(artifact: Artifact) -> bool:
    if artifact.worker_id != "impact_safety":
        return False
    impact = artifact.payload.get("impact_safety") or {}
    if impact.get("overall_risk_level") in {"high", "critical"}:
        return not (
            impact.get("safety_constraints") or impact.get("mandatory_checks")
        )
    return False


# 判断单条成功标准是否被非拒答制品覆盖：命中关键词的角色制品必须齐全。
def _criterion_covered(
    criterion: str,
    artifacts: Sequence[Artifact],
    mapping: dict[str, tuple[str, ...]],
) -> bool:
    relevant = [
        role
        for role, keywords in mapping.items()
        if any(keyword in criterion for keyword in keywords)
    ]
    if not relevant:
        # 未命中任何角色的通用标准：任一非拒答制品即可覆盖。
        return any(_refusal_reason(artifact) is None for artifact in artifacts)
    return all(
        any(
            artifact.worker_id == role and _refusal_reason(artifact) is None
            for artifact in artifacts
        )
        for role in relevant
    )
