import json

import pytest

from flowfix_agent.adapters.resource_planning_generator import (
    LangChainResourcePlanningGenerator,
)
from flowfix_agent.knowledge.models import SourceType
from flowfix_agent.planning.models import IncidentContext, TaskSpec
from flowfix_agent.planning.workers.resource_planning import (
    ResourcePlanningGenerationError,
)
from flowfix_agent.retrieval.models import Evidence


# 模拟可注入的异步链，按顺序返回固定输出。
class FakeChain:
    def __init__(self, outputs: list[str]) -> None:
        self.outputs = list(outputs)
        self.calls: list[dict] = []

    async def ainvoke(self, variables: dict) -> str:
        self.calls.append(variables)
        if not self.outputs:
            raise AssertionError("unexpected extra chain call")
        return self.outputs.pop(0)


def _evidence() -> Evidence:
    return Evidence(
        citation_id=1,
        chunk_id="chunk-1",
        source_id="chunk-1",
        source_type=SourceType.PLATFORM_DOC,
        source_version="1.0.0",
        title="手册",
        section_path="",
        content="内容",
        score=0.9,
        estimated_tokens=10,
    )


def _incident() -> IncidentContext:
    return IncidentContext(
        incident_id="i1",
        tenant_id="tenant-1",
        thread_id="thread-1",
        goal="规划备件目标",
        trace_id="trace-1",
    )


def _task() -> TaskSpec:
    return TaskSpec(
        task_id="resource",
        description="规划任务",
        required_role="resource_planning",
    )


def _valid_json() -> str:
    return json.dumps(
        {
            "primary_available": True,
            "confidence": 0.8,
            "candidates": [
                {
                    "candidate_id": "c1",
                    "kind": "spare_part",
                    "name": "2.5 寸 SATA 硬盘",
                    "description": "仓库库存充足。",
                    "available": True,
                    "supporting_evidence": [1],
                }
            ],
            "conflicts": [],
            "alternatives": [],
            "missing_info": ["备件到货时间"],
        },
        ensure_ascii=False,
    )


def _build() -> LangChainResourcePlanningGenerator:
    return LangChainResourcePlanningGenerator("k", "https://api.example.com/v1", "m", 10)


# 验证合法 JSON 直接解析，不触发 repair。
async def test_generator_parses_valid_json_without_repair():
    generator = _build()
    generator._chain = FakeChain([_valid_json()])
    generator._repair_chain = FakeChain([])

    result = await generator.generate(_incident(), _task(), [_evidence()])

    assert result.primary_available is True
    assert result.candidates[0].supporting_evidence == [1]
    assert result.confidence == 0.8
    assert generator._repair_chain.calls == []


# 验证首次输出非法时走一次 repair 并成功。
async def test_generator_repairs_invalid_json_once():
    generator = _build()
    generator._chain = FakeChain(["not json"])
    generator._repair_chain = FakeChain([_valid_json()])

    result = await generator.generate(_incident(), _task(), [_evidence()])

    assert result.primary_available is True
    assert len(generator._repair_chain.calls) == 1


# 验证两次输出都非法时 fail-closed 抛出异常。
async def test_generator_fail_closed_after_repair():
    generator = _build()
    generator._chain = FakeChain(["not json"])
    generator._repair_chain = FakeChain(["still not json"])

    with pytest.raises(ResourcePlanningGenerationError):
        await generator.generate(_incident(), _task(), [_evidence()])


# 验证 JSON 合法但引用未知编号时走 repair。
async def test_generator_repairs_unknown_citation():
    generator = _build()
    bad = json.dumps(
        {
            "primary_available": True,
            "confidence": 0.8,
            "candidates": [
                {
                    "candidate_id": "c1",
                    "kind": "spare_part",
                    "name": "备件",
                    "description": "说明。",
                    "available": True,
                    "supporting_evidence": [9],
                }
            ],
            "conflicts": [],
            "alternatives": [],
            "missing_info": [],
        },
        ensure_ascii=False,
    )
    generator._chain = FakeChain([bad])
    generator._repair_chain = FakeChain([_valid_json()])

    result = await generator.generate(_incident(), _task(), [_evidence()])

    assert result.candidates[0].supporting_evidence == [1]
    assert len(generator._repair_chain.calls) == 1


# 验证非法 kind 走 repair（kind 只能是 personnel/spare_part/window）。
async def test_generator_repairs_invalid_kind():
    generator = _build()
    bad = json.dumps(
        {
            "primary_available": True,
            "confidence": 0.8,
            "candidates": [
                {
                    "candidate_id": "c1",
                    "kind": "gold_bar",
                    "name": "备件",
                    "description": "说明。",
                    "available": True,
                    "supporting_evidence": [1],
                }
            ],
            "conflicts": [],
            "alternatives": [],
            "missing_info": [],
        },
        ensure_ascii=False,
    )
    generator._chain = FakeChain([bad])
    generator._repair_chain = FakeChain([_valid_json()])

    result = await generator.generate(_incident(), _task(), [_evidence()])

    assert result.candidates[0].kind.value == "spare_part"
    assert len(generator._repair_chain.calls) == 1


# 验证防御性剥离 markdown 代码围栏后再解析。
async def test_generator_strips_code_fence():
    generator = _build()
    generator._chain = FakeChain([f"```json\n{_valid_json()}\n```"])
    generator._repair_chain = FakeChain([])

    result = await generator.generate(_incident(), _task(), [_evidence()])

    assert result.primary_available is True


# 验证候选缺失来源时走 repair 并成功。
async def test_generator_repairs_missing_supporting_evidence():
    generator = _build()
    bad = json.dumps(
        {
            "primary_available": True,
            "confidence": 0.8,
            "candidates": [
                {
                    "candidate_id": "c1",
                    "kind": "spare_part",
                    "name": "备件",
                    "description": "说明。",
                    "available": True,
                    "supporting_evidence": [],
                }
            ],
            "conflicts": [],
            "alternatives": [],
            "missing_info": [],
        },
        ensure_ascii=False,
    )
    generator._chain = FakeChain([bad])
    generator._repair_chain = FakeChain([_valid_json()])

    result = await generator.generate(_incident(), _task(), [_evidence()])

    assert result.candidates[0].supporting_evidence == [1]
    assert len(generator._repair_chain.calls) == 1


# 验证主资源不可用时需带冲突与替代方案：缺失冲突时走 repair。
async def test_generator_repairs_missing_conflicts_when_unavailable():
    generator = _build()
    bad = json.dumps(
        {
            "primary_available": False,
            "confidence": 0.8,
            "candidates": [
                {
                    "candidate_id": "c1",
                    "kind": "spare_part",
                    "name": "电源模块",
                    "description": "库存在途未到。",
                    "available": False,
                    "supporting_evidence": [1],
                }
            ],
            "conflicts": [],
            "alternatives": [],
            "missing_info": [],
        },
        ensure_ascii=False,
    )
    generator._chain = FakeChain([bad])
    generator._repair_chain = FakeChain([_valid_json()])

    result = await generator.generate(_incident(), _task(), [_evidence()])

    assert result.primary_available is True
    assert len(generator._repair_chain.calls) == 1
