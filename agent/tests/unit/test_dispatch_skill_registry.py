from pathlib import Path

import pytest
from pydantic import ValidationError

from flowfix_agent.dispatch.adapters.skill_registry import FileDispatchSkillRegistry
from flowfix_agent.dispatch.skills.errors import (
    DispatchSkillRollbackError,
    DispatchSkillValidationError,
)
from flowfix_agent.dispatch.skills.loader import DispatchSkillLoader
from flowfix_agent.dispatch.skills.manifest import DispatchSkill, SkillLifecycle
from flowfix_agent.dispatch.skills.validator import validate_skill

BUILTIN = Path("src/flowfix_agent/dispatch/skills/builtin")


# 验证 Skill 激活、再次切换和回滚能正确维护生命周期。
def test_registry_activation_and_rollback_preserve_lifecycle(tmp_path: Path) -> None:
    skills = DispatchSkillLoader().load_directory(BUILTIN)
    registry = FileDispatchSkillRegistry(tmp_path / "registry.json")
    for skill in skills:
        registry.register(skill)

    registry.activate("balanced", "1.0.0")
    registry.activate("sla-first", "1.0.0")
    assert registry.get_active().skill_id == "sla-first"
    assert registry.get("balanced", "1.0.0").status == SkillLifecycle.RETIRED

    restored = registry.rollback()
    assert restored.skill_id == "balanced"
    assert restored.status == SkillLifecycle.ACTIVE
    assert registry.get("sla-first", "1.0.0").status == SkillLifecycle.RETIRED


# 验证不存在历史激活版本时注册表拒绝回滚。
def test_registry_rejects_rollback_without_prior_version(tmp_path: Path) -> None:
    skill = DispatchSkillLoader().load(BUILTIN / "balanced-v1.json")
    registry = FileDispatchSkillRegistry(tmp_path / "registry.json")
    registry.register(skill)
    registry.activate(skill.skill_id, skill.skill_version)
    with pytest.raises(DispatchSkillRollbackError):
        registry.rollback()


# 验证 Skill 的评分权重之和必须为一。
def test_skill_weights_must_sum_to_one() -> None:
    payload = DispatchSkillLoader().load(BUILTIN / "balanced-v1.json").model_dump(
        mode="json", exclude={"content_hash"}
    )
    payload["scoring_weights"]["distance"] = 0.5
    with pytest.raises(ValidationError, match="must sum to 1.0"):
        DispatchSkill.model_validate(payload)


# 验证 Skill 校验器拒绝未知快照字段和越权工具。
def test_skill_rejects_unknown_snapshot_field_and_tool() -> None:
    skill = DispatchSkillLoader().load(BUILTIN / "balanced-v1.json")
    invalid = skill.model_copy(
        update={
            "required_snapshot_fields": ["work_order.secret"],
            "tool_policy": skill.tool_policy.model_copy(
                update={"allowed_write_tools": ["run_arbitrary_python"]}
            ),
        }
    )
    with pytest.raises(DispatchSkillValidationError) as error:
        validate_skill(invalid)
    assert "unknown_snapshot_fields" in str(error.value)
    assert "unknown_write_tools" in str(error.value)


# 验证 Skill 声明不兼容的工具合同版本时校验失败。
def test_skill_rejects_incompatible_tool_contract() -> None:
    skill = DispatchSkillLoader().load(BUILTIN / "balanced-v1.json")
    invalid = skill.model_copy(
        update={
            "tool_policy": skill.tool_policy.model_copy(
                update={"contract_version": "dispatch-tools/v999"}
            )
        }
    )
    with pytest.raises(DispatchSkillValidationError, match="unsupported_tool_contract"):
        validate_skill(invalid)


# 验证加载器拒绝可执行文件和非 JSON 策略文件。
def test_loader_rejects_executable_or_non_json_skill(tmp_path: Path) -> None:
    path = tmp_path / "dangerous.py"
    path.write_text("raise RuntimeError('must never execute')", encoding="utf-8")
    with pytest.raises(DispatchSkillValidationError, match="Only declarative JSON"):
        DispatchSkillLoader().load(path)
