from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel


# 从 JSON Lines 文件加载并校验指定类型的评测数据。
def load_jsonl_dataset[EvaluationModel: BaseModel](
    path: Path,
    model_type: type[EvaluationModel],
    dataset_name: str,
) -> list[EvaluationModel]:
    cases: list[EvaluationModel] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            cases.append(model_type.model_validate_json(line))
        except Exception as exc:
            raise ValueError(
                f"Invalid {dataset_name} dataset line {line_number}: {path}"
            ) from exc
    if not cases:
        raise ValueError(f"{dataset_name.capitalize()} evaluation dataset is empty: {path}")
    return cases


# 计算结果行中指定布尔字段的通过率。
def boolean_rate(rows: list[dict], field: str) -> float:
    return round(sum(bool(row[field]) for row in rows) / len(rows), 4)


# 将评测报告以格式化 JSON 写入目标路径。
def write_json_report(report: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
