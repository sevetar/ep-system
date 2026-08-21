import json

from pydantic import BaseModel

from flowfix_agent.evaluation.common import (
    boolean_rate,
    load_jsonl_dataset,
    write_json_report,
)
from flowfix_agent.evaluation.qa import _ndcg, _unique


# 定义验证通用 JSONL 加载器所需的最小评测模型。
class SampleEvaluationCase(BaseModel):
    case_id: str


# 验证来源去重后仍保留首次出现的排名顺序。
def test_unique_preserves_first_source_rank():
    assert _unique(["a.md", "a.md", "b.md", "a.md"]) == ["a.md", "b.md"]


# 验证来源去重后的 nDCG 结果保持在合法范围内。
def test_ndcg_is_bounded_after_source_deduplication():
    retrieved = _unique(["a.md", "a.md", "b.md", "other.md"])

    score = _ndcg(retrieved, ["a.md", "b.md"])

    assert score == 1.0


# 验证通用评测组件能够加载数据、统计通过率并写入报告。
def test_common_evaluation_dataset_metrics_and_report(tmp_path):
    dataset = tmp_path / "cases.jsonl"
    dataset.write_text(
        '{"case_id":"case-1"}\n\n{"case_id":"case-2"}\n',
        encoding="utf-8",
    )

    cases = load_jsonl_dataset(dataset, SampleEvaluationCase, "sample")
    rate = boolean_rate([{"passed": True}, {"passed": False}], "passed")
    output = tmp_path / "reports" / "result.json"
    write_json_report({"cases": len(cases), "rate": rate}, output)

    assert [case.case_id for case in cases] == ["case-1", "case-2"]
    assert json.loads(output.read_text(encoding="utf-8")) == {
        "cases": 2,
        "rate": 0.5,
    }
