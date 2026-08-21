from __future__ import annotations

import re

from flowfix_agent.knowledge.models import KnowledgeQualityAssessment
from flowfix_agent.messaging.models import WorkOrderCompletedEvent


class WorkOrderKnowledgeQualityGate:
    """用确定性规则拦截低质量或带指令注入的案例，并在索引前脱敏。"""

    _sensitive_patterns = (
        ("email", re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I), "[已脱敏邮箱]"),
        ("phone", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"), "[已脱敏手机号]"),
        ("id_card", re.compile(r"(?<!\d)\d{17}[0-9Xx](?!\w)"), "[已脱敏证件号]"),
    )
    _injection_patterns = (
        re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.I),
        re.compile(r"system\s+prompt", re.I),
        re.compile(r"忽略.{0,8}(之前|以上).{0,8}指令"),
        re.compile(r"输出.{0,8}(系统提示词|system prompt)", re.I),
    )

    def sanitize(
        self, event: WorkOrderCompletedEvent
    ) -> tuple[WorkOrderCompletedEvent, list[str]]:
        redacted_fields: list[str] = []
        updates: dict[str, object] = {}
        for field in (
            "description",
            "repair_process",
            "solution",
            "root_cause",
            "verification_result",
            "replaced_parts",
        ):
            value = str(getattr(event, field, ""))
            sanitized = value
            for _, pattern, replacement in self._sensitive_patterns:
                sanitized = pattern.sub(replacement, sanitized)
            if sanitized != value:
                redacted_fields.append(field)
            updates[field] = sanitized.strip()
        sanitized_tags = [self._sanitize_text(item)[:80] for item in event.knowledge_tags]
        if sanitized_tags != event.knowledge_tags:
            redacted_fields.append("knowledge_tags")
        updates["knowledge_tags"] = [item for item in sanitized_tags if item]
        return event.model_copy(update=updates), sorted(set(redacted_fields))

    def assess(
        self, event: WorkOrderCompletedEvent, redacted_fields: list[str]
    ) -> KnowledgeQualityAssessment:
        score = 100
        issues: list[str] = []
        blocking = False

        checks = (
            ("description_too_short", event.description, 4, 25),
            ("repair_process_too_short", event.repair_process, 8, 30),
            ("solution_too_short", event.solution, 8, 30),
        )
        for issue, value, minimum, penalty in checks:
            if len(value.strip()) < minimum:
                issues.append(issue)
                score -= penalty
                blocking = True

        if event.schema_version.endswith("/v2") and len(event.verification_result.strip()) < 4:
            issues.append("verification_result_too_short")
            score -= 25
            blocking = True
        elif not event.verification_result.strip():
            issues.append("legacy_schema_missing_verification")
            score -= 15

        if not event.root_cause.strip():
            issues.append("root_cause_missing")
            score -= 10
        if not event.device_category.strip():
            issues.append("device_category_missing")
            score -= 5
        if not event.device_model.strip():
            issues.append("device_model_missing")
            score -= 5

        searchable_text = "\n".join(
            (
                event.description,
                event.repair_process,
                event.solution,
                event.root_cause,
                event.verification_result,
            )
        )
        if any(pattern.search(searchable_text) for pattern in self._injection_patterns):
            issues.append("prompt_injection_detected")
            score -= 50
            blocking = True

        score = max(0, score)
        return KnowledgeQualityAssessment(
            accepted=not blocking and score >= 65,
            score=score,
            issues=issues,
            redacted_fields=redacted_fields,
        )

    def _sanitize_text(self, value: str) -> str:
        sanitized = value.strip()
        for _, pattern, replacement in self._sensitive_patterns:
            sanitized = pattern.sub(replacement, sanitized)
        return sanitized
