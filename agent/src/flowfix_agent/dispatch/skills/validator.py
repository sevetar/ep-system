from __future__ import annotations

from flowfix_agent.dispatch.skills.errors import DispatchSkillValidationError
from flowfix_agent.dispatch.skills.manifest import DispatchSkill

SUPPORTED_SCHEMA = "dispatch-state/v1"
SUPPORTED_TOOL_CONTRACT = "dispatch-tools/v1"
SUPPORTED_SNAPSHOT_FIELDS = {
    "work_order.work_order_id",
    "work_order.tenant_id",
    "work_order.device_id",
    "work_order.region",
    "work_order.required_skills",
    "work_order.priority",
    "work_order.status",
    "work_order.version",
    "workers.worker_id",
    "workers.tenant_id",
    "workers.region",
    "workers.skills",
    "workers.shift_active",
    "workers.available",
    "workers.current_load",
    "workers.capacity",
    "workers.distance_km",
    "workers.sla_readiness",
}
ALLOWED_READ_TOOLS = {
    "get_work_order_snapshot",
    "list_eligible_workers",
    "get_worker_loads",
    "search_dispatch_policy",
    "get_assignment_outcome",
}
ALLOWED_WRITE_TOOLS = {
    "create_assignment",
    "publish_dispatch_audit",
}


# 校验策略使用的状态模式、快照字段和工具是否在允许范围内。
def validate_skill(skill: DispatchSkill) -> None:
    errors: list[str] = []
    if skill.compatible_schema != SUPPORTED_SCHEMA:
        errors.append(f"unsupported_schema:{skill.compatible_schema}")
    if skill.tool_policy.contract_version != SUPPORTED_TOOL_CONTRACT:
        errors.append(
            f"unsupported_tool_contract:{skill.tool_policy.contract_version}"
        )
    unknown_fields = sorted(
        set(skill.required_snapshot_fields) - SUPPORTED_SNAPSHOT_FIELDS
    )
    if unknown_fields:
        errors.append(f"unknown_snapshot_fields:{','.join(unknown_fields)}")
    unknown_read_tools = sorted(
        set(skill.tool_policy.allowed_read_tools) - ALLOWED_READ_TOOLS
    )
    if unknown_read_tools:
        errors.append(f"unknown_read_tools:{','.join(unknown_read_tools)}")
    unknown_write_tools = sorted(
        set(skill.tool_policy.allowed_write_tools) - ALLOWED_WRITE_TOOLS
    )
    if unknown_write_tools:
        errors.append(f"unknown_write_tools:{','.join(unknown_write_tools)}")
    if errors:
        raise DispatchSkillValidationError(";".join(errors))
