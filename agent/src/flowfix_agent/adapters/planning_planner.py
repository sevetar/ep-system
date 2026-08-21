from __future__ import annotations

import json

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import ValidationError

from flowfix_agent.adapters.models import strip_code_fence
from flowfix_agent.core.errors import FlowFixError
from flowfix_agent.planning.models import IncidentContext, PlanDraft, TaskSpec
from flowfix_agent.planning.validation import PlanValidationError, PlanValidator

# 注意：JSON 示例中的花括号需转义为双花括号，避免被模板解析为占位符。
_SCHEMA_DOC = """\
JSON 结构如下：
{{
  "plan_id": "plan-<incident_id>",
  "tasks": [
    {{
      "task_id": "t1",
      "description": "任务描述",
      "required_role": "diagnosis",
      "dependencies": [],
      "allowed_capabilities": ["knowledge.search"]
    }}
  ]
}}
"""

# 只读调查规划允许的三类 Worker 角色白名单。
_PLANNER_ROLES = {"diagnosis", "impact_safety", "resource_planning"}

# 只读能力常量：规划产物中的每个任务都只允许调用知识检索。
_READ_CAPABILITY = "knowledge.search"


# 计划生成两次校验均失败时抛出的异常。
class PlannerGenerationError(FlowFixError):
    pass


# 使用 OpenAI 兼容接口生成受角色白名单约束的只读调查计划 JSON。
class LangChainPlanningPlanner:
    # 创建聊天模型、规划提示词、修复提示词与解析链。
    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float,
    ) -> None:
        # 统一复用同一个低随机性模型，确保首次生成与修复阶段的输出尽量稳定。
        chat = ChatOpenAI(
            api_key=api_key,
            base_url=base_url,
            model=model,
            temperature=0,
            timeout=timeout_seconds,
            max_retries=1,
        )
        # 系统提示词同时约束任务角色、能力范围、依赖关系和最终输出格式。
        system_prompt = (
            "你是 FlowFix 设备运维调查规划助手。为给定事故规划一个只读调查计划。"
            "只能从角色 diagnosis（根因诊断）、impact_safety（影响与安全评估）、"
            "resource_planning（资源规划）中选用任务角色；不得发明其他角色。"
            "每个任务的 allowed_capabilities 只能是 [\"knowledge.search\"]，"
            "禁止任何写能力（如 assignment.create）。任务依赖只能引用本计划内已定义"
            "的 task_id，且不得形成环；任务数量不能超过 max_tasks。输出必须是一个"
            "JSON 对象，不能包含 JSON 之外的任何文字，不能输出 markdown 代码块。\n"
            f"{_SCHEMA_DOC}"
        )
        # 首次生成提示词只注入事故上下文及计划规模限制。
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", system_prompt),
                (
                    "human",
                    "事故目标：{goal}\n成功标准：{success_criteria}\n"
                    "目标工单号：{dispatch_target}\n最大任务数：{max_tasks}\n"
                    "最大并行数：{max_parallel}\n\n请输出只读调查计划的 JSON。",
                ),
            ]
        )
        # 修复提示词额外提供原始输出和校验错误，引导模型做最小结构调整。
        repair_prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "修复以下调查计划 JSON。只能调整任务结构、角色与依赖使其通过校验，"
                    "不要引入写能力或白名单之外的未知角色。",
                ),
                (
                    "human",
                    "事故目标：{goal}\n成功标准：{success_criteria}\n"
                    "目标工单号：{dispatch_target}\n最大任务数：{max_tasks}\n"
                    "最大并行数：{max_parallel}\n\n校验错误：{error}\n\n"
                    "原输出：\n{draft}\n\n输出修复后的 JSON。",
                ),
            ]
        )
        # 将模型消息统一转成字符串，并分别构建生成链与一次性修复链。
        parser = StrOutputParser()
        self._chain = prompt | chat | parser
        self._repair_chain = repair_prompt | chat | parser
        self.model = model

    # 根据事故上下文生成通过 PlanValidator 校验的只读计划草稿。
    async def plan(self, incident: IncidentContext) -> PlanDraft:
        # 组装模型输入变量：空列表/None 归一化为可读的占位文本。
        variables = {
            "goal": incident.goal,
            "success_criteria": "；".join(incident.success_criteria) or "无",
            "dispatch_target": incident.dispatch_target or "无",
            "max_tasks": str(incident.max_tasks),
            "max_parallel": str(incident.max_parallel),
        }
        # 首次生成：模型输出计划 JSON，随后解析并按白名单校验。
        draft = await self._chain.ainvoke(variables)
        result, error = self._parse_and_validate(draft, incident)
        if result is not None:
            return result
        # 校验失败时携带错误信息触发一次修复；仍失败则 fail-closed 抛错。
        repaired = await self._repair_chain.ainvoke(
            {**variables, "draft": draft, "error": error}
        )
        result, repair_error = self._parse_and_validate(repaired, incident)
        if result is not None:
            return result
        raise PlannerGenerationError(
            f"plan output invalid after repair: {repair_error or error}"
        )

    # 解析并校验模型输出：剥围栏、JSON 解析、Schema 校验、角色白名单与确定性归一化。
    @staticmethod
    def _parse_and_validate(
        text: str, incident: IncidentContext
    ) -> tuple[PlanDraft | None, str | None]:
        # 兼容模型偶尔返回的 Markdown 代码围栏，再进行严格 JSON 解析。
        cleaned = strip_code_fence(text)
        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            return None, f"invalid json: {exc}"
        try:
            draft = PlanDraft.model_validate(payload)
        except ValidationError as exc:
            return None, f"schema invalid: {exc}"
        # 在依赖映射前拒绝重复 ID，避免归一化时发生键覆盖。
        ids = [task.task_id for task in draft.tasks]
        if len(ids) != len(set(ids)):
            return None, "duplicate task ids"
        # 显式检查角色白名单，为模型生成的未知角色返回可修复的错误信息。
        roles = {task.required_role for task in draft.tasks}
        unknown = sorted(roles - _PLANNER_ROLES)
        if unknown:
            return None, f"unknown roles: {unknown}"
        # 先统一标识与能力，再执行包含数量、依赖和并发约束的完整校验。
        draft = LangChainPlanningPlanner._normalize(incident, draft)
        try:
            PlanValidator().validate(incident, draft)
        except PlanValidationError as exc:
            return None, f"plan invalid: {exc}"
        return draft, None

    # 确定性归一化：固定 plan_id、重排 task_id、重写依赖、剥离写能力。
    @staticmethod
    def _normalize(incident: IncidentContext, draft: PlanDraft) -> PlanDraft:
        # 按模型给出的任务顺序生成连续 ID，并保留旧 ID 到新 ID 的映射。
        ordered = [task.task_id for task in draft.tasks]
        old_to_new = {
            old: f"t{index}" for index, old in enumerate(ordered, start=1)
        }
        # 重建任务以同步改写依赖，并强制收敛到唯一的只读能力。
        tasks = [
            TaskSpec(
                task_id=old_to_new[task.task_id],
                description=task.description,
                required_role=task.required_role,
                dependencies=[old_to_new[dep] for dep in task.dependencies],
                allowed_capabilities={_READ_CAPABILITY},
            )
            for task in draft.tasks
        ]
        # plan_id 由事故 ID 派生，避免采信模型生成的不稳定标识。
        return PlanDraft(plan_id=f"plan-{incident.incident_id}", tasks=tasks)
