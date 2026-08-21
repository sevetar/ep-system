import json

import pytest

from flowfix_agent.adapters.impact_safety_generator import (
    LangChainImpactSafetyGenerator,
)
from flowfix_agent.knowledge.models import SourceType
from flowfix_agent.planning.models import IncidentContext, TaskSpec
from flowfix_agent.planning.workers.impact_safety import ImpactSafetyGenerationError
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
        goal="评估目标",
        trace_id="trace-1",
    )


def _task() -> TaskSpec:
    return TaskSpec(
        task_id="impact",
        description="评估任务",
        required_role="impact_safety",
    )


def _valid_json() -> str:
    return json.dumps(
        {
            "overall_risk_level": "high",
            "confidence": 0.8,
            "impact_scopes": [
                {
                    "scope_id": "s1",
                    "target": "受影响设备",
                    "description": "故障导致目标受影响。",
                    "supporting_evidence": [1],
                }
            ],
            "risks": [
                {
                    "risk_id": "r1",
                    "title": "影响扩大化",
                    "description": "故障可能扩大影响范围。",
                    "severity": "high",
                    "supporting_evidence": [1],
                }
            ],
            "safety_constraints": [
                {
                    "constraint_id": "c1",
                    "action": "禁止带电检修。",
                    "rationale": "防止人身伤害。",
                    "supporting_evidence": [1],
                }
            ],
            "mandatory_checks": [
                {
                    "check_id": "m1",
                    "item": "处置前确认设备已隔离。",
                    "supporting_evidence": [1],
                }
            ],
            "missing_info": ["现场巡检数据"],
        },
        ensure_ascii=False,
    )


def _build() -> LangChainImpactSafetyGenerator:
    return LangChainImpactSafetyGenerator("k", "https://api.example.com/v1", "m", 10)


# 验证合法 JSON 直接解析，不触发 repair。
async def test_generator_parses_valid_json_without_repair():
    generator = _build()
    generator._chain = FakeChain([_valid_json()])
    generator._repair_chain = FakeChain([])

    result = await generator.generate(_incident(), _task(), [_evidence()])

    assert result.overall_risk_level.value == "high"
    assert result.impact_scopes[0].supporting_evidence == [1]
    assert result.risks[0].severity.value == "high"
    assert result.confidence == 0.8
    assert generator._repair_chain.calls == []


# 验证首次输出非法时走一次 repair 并成功。
async def test_generator_repairs_invalid_json_once():
    generator = _build()
    generator._chain = FakeChain(["not json"])
    generator._repair_chain = FakeChain([_valid_json()])

    result = await generator.generate(_incident(), _task(), [_evidence()])

    assert result.overall_risk_level.value == "high"
    assert len(generator._repair_chain.calls) == 1


# 验证两次输出都非法时 fail-closed 抛出异常。
async def test_generator_fail_closed_after_repair():
    generator = _build()
    generator._chain = FakeChain(["not json"])
    generator._repair_chain = FakeChain(["still not json"])

    with pytest.raises(ImpactSafetyGenerationError):
        await generator.generate(_incident(), _task(), [_evidence()])


# 验证 JSON 合法但引用未知编号时走 repair。
async def test_generator_repairs_unknown_citation():
    generator = _build()
    bad = json.dumps(
        {
            "overall_risk_level": "high",
            "confidence": 0.8,
            "impact_scopes": [],
            "risks": [
                {
                    "risk_id": "r1",
                    "title": "影响扩大化",
                    "description": "说明。",
                    "severity": "high",
                    "supporting_evidence": [9],
                }
            ],
            "safety_constraints": [],
            "mandatory_checks": [],
            "missing_info": [],
        },
        ensure_ascii=False,
    )
    generator._chain = FakeChain([bad])
    generator._repair_chain = FakeChain([_valid_json()])

    result = await generator.generate(_incident(), _task(), [_evidence()])

    assert result.risks[0].supporting_evidence == [1]
    assert len(generator._repair_chain.calls) == 1


# 验证防御性剥离 markdown 代码围栏后再解析。
async def test_generator_strips_code_fence():
    generator = _build()
    generator._chain = FakeChain([f"```json\n{_valid_json()}\n```"])
    generator._repair_chain = FakeChain([])

    result = await generator.generate(_incident(), _task(), [_evidence()])

    assert result.overall_risk_level.value == "high"


# 验证「不能降风险」：整体等级低于已识别风险时触发 repair 并成功修复。
async def test_generator_repairs_lowered_risk():
    generator = _build()
    lowered = json.dumps(
        {
            "overall_risk_level": "low",
            "confidence": 0.8,
            "impact_scopes": [],
            "risks": [
                {
                    "risk_id": "r1",
                    "title": "连锁爆炸风险",
                    "description": "风险说明。",
                    "severity": "critical",
                    "supporting_evidence": [1],
                }
            ],
            "safety_constraints": [],
            "mandatory_checks": [],
            "missing_info": [],
        },
        ensure_ascii=False,
    )
    generator._chain = FakeChain([lowered])
    generator._repair_chain = FakeChain([_valid_json()])

    result = await generator.generate(_incident(), _task(), [_evidence()])

    assert result.overall_risk_level.value == "high"
    assert len(generator._repair_chain.calls) == 1


# 验证「不能降风险」修复后仍非法时 fail-closed 抛出异常。
async def test_generator_fail_closed_on_lowered_risk_after_repair():
    generator = _build()
    lowered = json.dumps(
        {
            "overall_risk_level": "low",
            "confidence": 0.8,
            "impact_scopes": [],
            "risks": [
                {
                    "risk_id": "r1",
                    "title": "连锁爆炸风险",
                    "description": "风险说明。",
                    "severity": "critical",
                    "supporting_evidence": [1],
                }
            ],
            "safety_constraints": [],
            "mandatory_checks": [],
            "missing_info": [],
        },
        ensure_ascii=False,
    )
    generator._chain = FakeChain([lowered])
    generator._repair_chain = FakeChain([lowered])

    with pytest.raises(ImpactSafetyGenerationError):
        await generator.generate(_incident(), _task(), [_evidence()])
