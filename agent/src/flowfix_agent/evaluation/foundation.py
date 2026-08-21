from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from flowfix_agent.routing import RequestRouter


# 在固定数据集上运行 Phase A Router 评测并返回含门禁的报告。
def evaluate_router(dataset: Path | str) -> dict[str, Any]:
    # 统一将路径转为 Path 对象，兼容 str 入参。
    dataset = Path(dataset)
    # 创建确定性路由实例（Phase A 评测不依赖模型）。
    router = RequestRouter()
    # cases 记录每条用例的路由结果；source_cases 保留原始用例，供混淆矩阵等统计使用。
    cases: list[dict[str, Any]] = []
    source_cases: list[dict[str, Any]] = []
    # 逐行解析 JSONL：空行跳过，其余每一行视为一条用例。
    for line in dataset.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        source_cases.append(item)
        # 对输入做路由，trace_id 用于串联评测日志。
        result = router.route(item["message"], trace_id=f"eval-{item['id']}")
        # 路由链路是否与期望一致。
        route_ok = result.route_type.value == item["expected_route"]
        # 缺失字段集合是否与期望一致（用例未声明时为期望空集合）。
        missing_ok = set(result.missing_fields) == set(item.get("missing_fields", []))
        # 记录该用例的单项结果，供门禁与报告使用。
        cases.append(
            {
                "id": item["id"],
                "route": result.route_type.value,
                "route_ok": route_ok,
                "missing_fields_ok": missing_ok,
                "passed": route_ok and missing_ok,
            }
        )
    # 统计全部通过的用例数。
    passed = sum(case["passed"] for case in cases)
    # 合并期望与预测中出现过的所有路由标签，保证混淆矩阵行列一致。
    labels = sorted(
        {item["expected_route"] for item in source_cases}
        | {case["route"] for case in cases}
    )
    # 构建混淆矩阵：confusion[期望标签][实际标签] = 命中数。
    confusion = {
        expected: {
            predicted: sum(
                item["expected_route"] == expected and case["route"] == predicted
                for item, case in zip(source_cases, cases, strict=True)
            )
            for predicted in labels
        }
        for expected in labels
    }
    per_route = {}
    f1_scores = []
    # 逐链路计算 P/R/F1，并收集各链路 F1 用于最终宏观平均。
    for label in labels:
        tp = confusion[label][label]
        support = sum(confusion[label].values())
        predicted = sum(confusion[expected][label] for expected in labels)
        precision = tp / predicted if predicted else 0.0
        recall = tp / support if support else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        f1_scores.append(f1)
        per_route[label] = {
            "support": support,
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
        }
    # 危险误派：期望非派单、却被判成 DIRECT_DISPATCH 的用例数。
    dangerous_misroutes = sum(
        item["expected_route"] != "DIRECT_DISPATCH"
        and case["route"] == "DIRECT_DISPATCH"
        for item, case in zip(source_cases, cases, strict=True)
    )
    # 组装评测报告：指标 + 门禁结果，供 CLI 打印与落盘。
    return {
        "dataset": str(dataset),
        "total": len(cases),
        "passed": passed,
        "accuracy": passed / len(cases) if cases else 0,
        "macro_f1": round(sum(f1_scores) / len(f1_scores), 4) if f1_scores else 0,
        "class_distribution": dict(Counter(item["expected_route"] for item in source_cases)),
        "per_route": per_route,
        "confusion_matrix": confusion,
        "dangerous_misroute_count": dangerous_misroutes,
        "gate": {
            # 门禁判定：全部用例通过且无危险误派才算通过。
            "passed": passed == len(cases) and dangerous_misroutes == 0,
            "criteria": {"accuracy": 1.0, "dangerous_misroute_count": 0},
        },
        "cases": cases,
    }


# 将 Phase A 评测报告以 JSON 写入指定输出文件。
def write_foundation_report(report: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
