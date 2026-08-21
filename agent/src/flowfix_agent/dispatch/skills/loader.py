from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from flowfix_agent.dispatch.skills.errors import DispatchSkillValidationError
from flowfix_agent.dispatch.skills.manifest import DispatchSkill
from flowfix_agent.dispatch.skills.validator import validate_skill


# 负责从声明式 JSON 文件加载并校验调度策略。
class DispatchSkillLoader:
    # 加载单个 JSON 策略文件并转换为领域模型。
    def load(self, path: Path) -> DispatchSkill:
        if path.suffix.lower() != ".json":
            raise DispatchSkillValidationError(
                f"Only declarative JSON skills are supported in M3: {path}"
            )
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            skill = DispatchSkill.model_validate(payload)
        except (OSError, json.JSONDecodeError, ValidationError) as exc:
            raise DispatchSkillValidationError(f"Invalid skill manifest: {path}") from exc
        validate_skill(skill)
        return skill

    # 按文件名顺序加载目录内的全部策略并检查版本键重复。
    def load_directory(self, directory: Path) -> list[DispatchSkill]:
        if not directory.is_dir():
            raise DispatchSkillValidationError(f"Skill directory does not exist: {directory}")
        paths = sorted(directory.glob("*.json"))
        if not paths:
            raise DispatchSkillValidationError(f"No JSON skills found in: {directory}")
        skills = [self.load(path) for path in paths]
        keys = [skill.key for skill in skills]
        if len(keys) != len(set(keys)):
            raise DispatchSkillValidationError("Duplicate skill id/version in directory")
        return skills
