from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path

from flowfix_agent.dispatch.skills.errors import (
    DispatchSkillNotFoundError,
    DispatchSkillRollbackError,
    DispatchSkillValidationError,
)
from flowfix_agent.dispatch.skills.manifest import DispatchSkill, SkillLifecycle
from flowfix_agent.dispatch.skills.validator import validate_skill


# 通过本地 JSON 文件持久化调度策略及其激活历史。
class FileDispatchSkillRegistry:
    """使用原子文件写入并维护单一激活指针的本地 Skill 注册表。"""

    # 初始化注册表文件路径和进程内可重入锁。
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()

    # 以草稿状态注册策略，并阻止同版本内容被覆盖。
    def register(self, skill: DispatchSkill) -> None:
        validate_skill(skill)
        with self._lock:
            payload = self._read()
            existing = payload["skills"].get(skill.key)
            if existing:
                registered = DispatchSkill.model_validate(existing)
                if registered.content_hash != skill.content_hash:
                    raise DispatchSkillValidationError(
                        f"Skill version already exists with different content: {skill.key}"
                    )
                return
            draft = skill.model_copy(update={"status": SkillLifecycle.DRAFT})
            payload["skills"][skill.key] = draft.model_dump(mode="json")
            self._write(payload)

    # 根据策略标识和版本读取策略及其当前生命周期状态。
    def get(self, skill_id: str, skill_version: str) -> DispatchSkill:
        with self._lock:
            payload = self._read()
            key = f"{skill_id}:{skill_version}"
            raw = payload["skills"].get(key)
            if not raw:
                raise DispatchSkillNotFoundError(f"Dispatch skill not found: {key}")
            return self._with_lifecycle(payload, key, raw)

    # 按注册键排序返回全部策略。
    def list_skills(self) -> list[DispatchSkill]:
        with self._lock:
            payload = self._read()
            return [
                self._with_lifecycle(payload, key, raw)
                for key, raw in sorted(payload["skills"].items())
            ]

    # 返回当前激活的策略。
    def get_active(self) -> DispatchSkill:
        with self._lock:
            payload = self._read()
            key = payload.get("active_key")
            if not key:
                raise DispatchSkillNotFoundError("No active dispatch skill")
            raw = payload["skills"].get(key)
            if not raw:
                raise DispatchSkillNotFoundError(f"Active dispatch skill missing: {key}")
            return self._with_lifecycle(payload, key, raw)

    # 激活指定策略版本并记录激活历史和回滚栈。
    def activate(self, skill_id: str, skill_version: str) -> DispatchSkill:
        with self._lock:
            payload = self._read()
            key = f"{skill_id}:{skill_version}"
            raw = payload["skills"].get(key)
            if not raw:
                raise DispatchSkillNotFoundError(f"Dispatch skill not found: {key}")
            if payload.get("active_key") != key:
                payload["active_key"] = key
                payload["activation_history"].append(key)
                payload["active_stack"].append(key)
                self._write(payload)
            return self._with_lifecycle(payload, key, raw)

    # 将当前策略回滚到激活栈中的上一个版本。
    def rollback(self) -> DispatchSkill:
        with self._lock:
            payload = self._read()
            stack = payload["active_stack"]
            if len(stack) < 2:
                raise DispatchSkillRollbackError("No prior dispatch skill activation")
            stack.pop()
            payload["active_key"] = stack[-1]
            self._write(payload)
            key = payload["active_key"]
            return self._with_lifecycle(payload, key, payload["skills"][key])

    # 根据当前激活项和历史记录计算策略的生命周期状态。
    @staticmethod
    def _with_lifecycle(payload: dict, key: str, raw: dict) -> DispatchSkill:
        active_key = payload.get("active_key")
        activated = set(payload.get("activation_history", []))
        if key == active_key:
            status = SkillLifecycle.ACTIVE
        elif key in activated:
            status = SkillLifecycle.RETIRED
        else:
            status = SkillLifecycle.DRAFT
        return DispatchSkill.model_validate({**raw, "status": status})

    # 读取注册表文件，并为缺失字段补齐兼容默认值。
    def _read(self) -> dict:
        if not self.path.exists():
            return {
                "schema_version": 1,
                "skills": {},
                "active_key": None,
                "activation_history": [],
                "active_stack": [],
            }
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        payload.setdefault("skills", {})
        payload.setdefault("active_key", None)
        payload.setdefault("activation_history", [])
        # 老格式中 activation_history 同时承担回滚栈；读取时无损迁移。
        payload.setdefault("active_stack", list(payload["activation_history"]))
        return payload

    # 通过临时文件替换方式原子写入注册表内容。
    def _write(self, payload: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            dir=self.path.parent,
            prefix=f".{self.path.name}.",
            suffix=".tmp",
            text=True,
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, self.path)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)
