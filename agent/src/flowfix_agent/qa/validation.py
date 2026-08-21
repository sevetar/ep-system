from __future__ import annotations

import re
from collections.abc import Sequence

from flowfix_agent.qa.models import ValidationResult
from flowfix_agent.retrieval.models import Evidence

CITATION_PATTERN = re.compile(r"\[(\d+)]")


# 校验答案非空、包含引用且所有引用编号均来自实际证据。
def validate_citations(answer: str, evidence: Sequence[Evidence]) -> ValidationResult:
    cited_ids = list(dict.fromkeys(int(value) for value in CITATION_PATTERN.findall(answer)))
    allowed = {item.citation_id for item in evidence}
    errors: list[str] = []
    if not answer.strip():
        errors.append("empty_answer")
    if not cited_ids:
        errors.append("missing_citation")
    invalid = sorted(set(cited_ids) - allowed)
    if invalid:
        errors.append(f"unknown_citations:{','.join(map(str, invalid))}")
    return ValidationResult(valid=not errors, cited_ids=cited_ids, errors=errors)
