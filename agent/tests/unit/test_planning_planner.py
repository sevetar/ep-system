import json

import pytest

from flowfix_agent.adapters.planning_planner import (
    LangChainPlanningPlanner,
    PlannerGenerationError,
)
from flowfix_agent.planning.models import IncidentContext


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


def _incident() -> IncidentContext:
    return IncidentContext(
        incident_id="i1",
        tenant_id="tenant-1",
        thread_id="thread-1",
        goal="定位设备停机根因并评估影响",
        trace_id="trace-1",
        success_criteria=["定位根因", "评估影响范围"],
    )


def _valid_json() -> str:
    return json.dumps(
        {
            "plan_id": "anything",
            "tasks": [
                {
                    "task_id": "impact",
                    "description": "评估影响",
                    "required_role": "impact_safety",
                    "dependencies": [],
                    "allowed_capabilities": ["knowledge.search"],
                },
                {
                    "task_id": "diag",
                    "description": "诊断根因",
                    "required_role": "diagnosis",
                    "dependencies": ["impact"],
                    "allowed_capabilities": ["knowledge.search"],
                },
            ],
        },
        ensure_ascii=False,
    )


def _build() -> LangChainPlanningPlanner:
    return LangChainPlanningPlanner("k", "https://api.example.com/v1", "m", 10)


# 验证合法 JSON 直接解析，不触发 repair，并完成确定性归一化。
async def test_planner_parses_valid_json_without_repair():
    planner = _build()
    planner._chain = FakeChain([_valid_json()])
    planner._repair_chain = FakeChain([])

    draft = await planner.plan(_incident())

    assert draft.plan_id == "plan-i1"
    assert [task.task_id for task in draft.tasks] == ["t1", "t2"]
    assert draft.tasks[0].required_role == "impact_safety"
    assert draft.tasks[1].dependencies == ["t1"]
    assert draft.tasks[0].allowed_capabilities == {"knowledge.search"}
    assert planner._repair_chain.calls == []


# 验证首次输出非法时走一次 repair 并成功。
async def test_planner_repairs_invalid_json_once():
    planner = _build()
    planner._chain = FakeChain(["not json"])
    planner._repair_chain = FakeChain([_valid_json()])

    draft = await planner.plan(_incident())

    assert draft.plan_id == "plan-i1"
    assert len(planner._repair_chain.calls) == 1


# 验证两次输出都非法时 fail-closed 抛出异常。
async def test_planner_fail_closed_after_repair():
    planner = _build()
    planner._chain = FakeChain(["not json"])
    planner._repair_chain = FakeChain(["still not json"])

    with pytest.raises(PlannerGenerationError):
        await planner.plan(_incident())


# 验证模型输出的写能力被确定性剥离。
async def test_planner_strips_write_capability():
    planner = _build()
    raw = json.dumps(
        {
            "plan_id": "p",
            "tasks": [
                {
                    "task_id": "diag",
                    "description": "诊断",
                    "required_role": "diagnosis",
                    "dependencies": [],
                    "allowed_capabilities": ["knowledge.search", "assignment.create"],
                }
            ],
        }
    )
    planner._chain = FakeChain([raw])
    planner._repair_chain = FakeChain([])

    draft = await planner.plan(_incident())

    assert draft.tasks[0].allowed_capabilities == {"knowledge.search"}
    assert planner._repair_chain.calls == []


# 验证未知角色触发 repair。
async def test_planner_repairs_unknown_role():
    planner = _build()
    raw = json.dumps(
        {
            "plan_id": "p",
            "tasks": [
                {
                    "task_id": "t1",
                    "description": "部署",
                    "required_role": "deployment",
                    "dependencies": [],
                    "allowed_capabilities": ["knowledge.search"],
                }
            ],
        }
    )
    planner._chain = FakeChain([raw])
    planner._repair_chain = FakeChain([_valid_json()])

    draft = await planner.plan(_incident())

    assert draft.plan_id == "plan-i1"
    assert len(planner._repair_chain.calls) == 1


# 验证环形依赖触发 PlanValidator 校验失败后经 repair 修复。
async def test_planner_repairs_cycle():
    planner = _build()
    raw = json.dumps(
        {
            "plan_id": "p",
            "tasks": [
                {
                    "task_id": "a",
                    "description": "任务 A",
                    "required_role": "diagnosis",
                    "dependencies": ["b"],
                    "allowed_capabilities": ["knowledge.search"],
                },
                {
                    "task_id": "b",
                    "description": "任务 B",
                    "required_role": "diagnosis",
                    "dependencies": ["a"],
                    "allowed_capabilities": ["knowledge.search"],
                },
            ],
        }
    )
    planner._chain = FakeChain([raw])
    planner._repair_chain = FakeChain([_valid_json()])

    draft = await planner.plan(_incident())

    assert len(planner._repair_chain.calls) == 1
    assert [task.task_id for task in draft.tasks] == ["t1", "t2"]


# 验证防御性剥离 markdown 代码围栏后再解析。
async def test_planner_strips_code_fence():
    planner = _build()
    planner._chain = FakeChain([f"```json\n{_valid_json()}\n```"])
    planner._repair_chain = FakeChain([])

    draft = await planner.plan(_incident())

    assert draft.plan_id == "plan-i1"
