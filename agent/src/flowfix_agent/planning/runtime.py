from __future__ import annotations

import asyncio
from typing import Literal, TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from flowfix_agent.memory.ports import TaskArtifactStorePort
from flowfix_agent.memory.task_artifact import TaskArtifactRecord
from flowfix_agent.planning.completion import (
    CompletionGate,
    build_dispatch_proposal,
)
from flowfix_agent.planning.controller import PlanController
from flowfix_agent.planning.models import (
    Artifact,
    CommittedPlan,
    DispatchProposal,
    IncidentContext,
    PlanningHumanInput,
    PlanningResult,
    PlanningStatus,
    ReplanTrigger,
    SupervisorAction,
    TaskSpec,
    TaskStatus,
)
from flowfix_agent.planning.ports import (
    PlannerPort,
    ReplanDetectorPort,
    ReplannerPort,
)
from flowfix_agent.planning.registry import WorkerRegistry
from flowfix_agent.planning.validation import PlanValidationError


# 规划运行时状态：事故、计划、状态表、制品、动作与报告。
class PlanningState(TypedDict, total=False):
    incident: IncidentContext
    plan: CommittedPlan
    statuses: dict[str, str]
    artifacts: list[Artifact]
    action: SupervisorAction
    ready_task_ids: list[str]
    failed_task_ids: list[str]
    replan_count: int
    replan_trigger: dict | None
    completion_reasons: list[str]
    proposal: DispatchProposal | None
    report: str
    final_status: str
    human_input: dict


# 五节点规划控制面：plan/supervise/execute_batch/replan/finalize。
class PlanningRuntime:
    # 组装五节点 LangGraph：按监督动作在 execute/replan/finalize 间路由。
    def __init__(
        self,
        planner: PlannerPort,
        controller: PlanController,
        workers: WorkerRegistry,
        store: TaskArtifactStorePort,
        replanner: ReplannerPort | None = None,
        detector: ReplanDetectorPort | None = None,
        completion_gate: CompletionGate | None = None,
        # 允许的最大重规划次数，默认 1 次与历史行为一致。
        max_replans: int = 1,
        checkpointer: BaseCheckpointSaver | None = None,
    ) -> None:
        self.planner = planner
        self.controller = controller
        self.workers = workers
        self.store = store
        self.replanner = replanner
        self.detector = detector
        self.max_replans = max_replans
        # 完成门禁为可选策略：注入后任务全完成时必须通过门禁才算完成，否则转人工。
        self.completion_gate = completion_gate
        graph = StateGraph(PlanningState)
        graph.add_node("plan", self._plan)
        graph.add_node("supervise", self._supervise)
        graph.add_node("execute_batch", self._execute_batch)
        graph.add_node("replan", self._replan)
        graph.add_node("request_human_input", self._request_human_input)
        graph.add_node("finalize", self._finalize)
        graph.add_edge(START, "plan")
        graph.add_edge("plan", "supervise")
        graph.add_conditional_edges(
            "supervise",
            self._route_supervisor,
            {
                "execute_batch": "execute_batch",
                "replan": "replan",
                "request_human_input": "request_human_input",
                "finalize": "finalize",
            },
        )
        graph.add_edge("execute_batch", "supervise")
        graph.add_edge("replan", "supervise")
        graph.add_conditional_edges(
            "request_human_input",
            self._route_human_input,
            {"supervise": "supervise", "finalize": "finalize"},
        )
        graph.add_edge("finalize", END)
        self.checkpointer = checkpointer or InMemorySaver()
        self.graph = graph.compile(checkpointer=self.checkpointer)

    # 以给定事故上下文驱动整个图并返回 PlanningResult。
    async def run(self, incident: IncidentContext) -> PlanningResult:
        thread_id = self._thread_id(incident)
        output = await self.graph.ainvoke(
            {"incident": incident, "artifacts": [], "replan_count": 0},
            config=self._config(thread_id),
        )
        return await self._result(thread_id, output)

    # 从持久检查点恢复人工补充后的原规划执行。
    async def resume(
        self,
        thread_id: str,
        human_input: PlanningHumanInput,
        *,
        tenant_id: str | None = None,
    ) -> PlanningResult:
        await self._require_tenant(thread_id, tenant_id)
        output = await self.graph.ainvoke(
            Command(resume=human_input.model_dump(mode="json")), self._config(thread_id)
        )
        return await self._result(thread_id, output)

    # 查询规划线程当前状态，不暴露内部图状态。
    async def status(
        self, thread_id: str, *, tenant_id: str | None = None
    ) -> PlanningResult:
        await self._require_tenant(thread_id, tenant_id)
        snapshot = await self.graph.aget_state(self._config(thread_id))
        if not snapshot.values:
            raise PlanValidationError(f"planning thread not found: {thread_id}")
        return await self._result(thread_id, dict(snapshot.values))

    async def _result(self, thread_id: str, output: dict) -> PlanningResult:
        snapshot = await self.graph.aget_state(self._config(thread_id))
        state = dict(snapshot.values or output)
        is_interrupted = bool(getattr(snapshot, "interrupts", ())) or "__interrupt__" in output
        plan = state["plan"]
        status = (
            PlanningStatus.AWAITING_HUMAN
            if is_interrupted
            else PlanningStatus(state["final_status"])
        )
        report = state.get("report") or self._human_report(state)
        return PlanningResult(
            incident_id=state["incident"].incident_id,
            plan_id=plan.plan_id,
            plan_version=plan.version,
            status=status,
            artifacts=state["artifacts"],
            report=report,
            replan_count=state["replan_count"],
            proposal=state.get("proposal"),
            thread_id=thread_id,
            interrupted=is_interrupted,
        )

    # 计划节点：调用 Planner 生成草稿并版本化提交。
    async def _plan(self, state: PlanningState) -> dict:
        draft = await self.planner.plan(state["incident"])
        plan = self.controller.commit_initial(state["incident"], draft)
        return {
            "plan": plan,
            "statuses": {task.task_id: TaskStatus.PENDING.value for task in plan.tasks},
        }

    # 监督节点：根据状态计算下一步动作与就绪任务。
    async def _supervise(self, state: PlanningState) -> dict:
        statuses = state["statuses"]
        failed = [task_id for task_id, status in statuses.items() if status == "failed"]
        if failed:
            action = (
                SupervisorAction.REQUEST_REPLAN
                if self.replanner
                and state.get("replan_count", 0) < self.max_replans
                else SupervisorAction.FAIL
            )
            return {"action": action, "failed_task_ids": failed}
        # 内容触发：即使任务成功完成，只要当前版本制品命中重规划信号也请求一次 Replan。
        if (
            self.replanner
            and self.detector
            and state.get("replan_count", 0) < self.max_replans
        ):
            # 调用重规划检测器：结合当前事故、已生成计划、任务状态与制品内容，
            # 判断是否存在"任务全部成功但处置目标仍未达成"的内容级重规划信号。
            trigger = await self.detector.detect(
                state["incident"],
                state["plan"],
                statuses,
                state["artifacts"],
            )
            if trigger is not None:
                return {
                    "action": SupervisorAction.REQUEST_REPLAN,
                    # 把检测到的重规划触发原因序列化为 JSON 写入状态，供重规划节点参考。
                    "replan_trigger": trigger.model_dump(mode="json"),
                    "failed_task_ids": [],
                }
        if statuses and all(status == "completed" for status in statuses.values()):
            # 注入完成门禁时：必须通过门禁才算完成，否则转人工补充信息。
            if self.completion_gate is not None:
                # 调用完成门禁：对当前事故/计划/任务状态与制品做实质质量评估，
                # 判定处置目标是否真正达成（区别于任务执行的"成功"）。
                decision = self.completion_gate.evaluate(
                    state["incident"],
                    state["plan"],
                    statuses,
                    state["artifacts"],
                )
                if not decision.approved:
                    return {
                        "action": SupervisorAction.AWAIT_HUMAN,
                        "ready_task_ids": [],
                        "completion_reasons": decision.reasons,
                    }
                return {
                    "action": SupervisorAction.COMPLETE,
                    "ready_task_ids": [],
                    "completion_reasons": decision.reasons,
                }
            return {"action": SupervisorAction.COMPLETE, "ready_task_ids": []}
        completed = {task_id for task_id, status in statuses.items() if status == "completed"}
        ready = [
            task.task_id
            for task in state["plan"].tasks
            if statuses.get(task.task_id) == "pending"
            and set(task.dependencies) <= completed
        ][: state["incident"].max_parallel]
        if not ready:
            return {"action": SupervisorAction.AWAIT_HUMAN, "ready_task_ids": []}
        return {"action": SupervisorAction.EXECUTE_BATCH, "ready_task_ids": ready}

    # 将监督动作映射到图的下一个节点。
    @staticmethod
    def _route_supervisor(
        state: PlanningState,
    ) -> Literal["execute_batch", "replan", "request_human_input", "finalize"]:
        if state["action"] is SupervisorAction.EXECUTE_BATCH:
            return "execute_batch"
        if state["action"] is SupervisorAction.REQUEST_REPLAN:
            return "replan"
        if state["action"] is SupervisorAction.AWAIT_HUMAN:
            return "request_human_input"
        return "finalize"

    # 真正暂停 Graph，并只暴露补充原因与允许的动作。
    async def _request_human_input(self, state: PlanningState) -> dict:
        payload = {
            "incident_id": state["incident"].incident_id,
            "reasons": state.get("completion_reasons", []),
            "allowed_actions": ["retry", "cancel"],
        }
        human_input = PlanningHumanInput.model_validate(interrupt(payload))
        if human_input.action == "cancel":
            return {
                "human_input": human_input.model_dump(mode="json"),
                "action": SupervisorAction.FAIL,
            }
        incident = state["incident"].model_copy(
            update={
                "goal": f"{state['incident'].goal}\n人工补充：{human_input.information}"
            }
        )
        return {
            "human_input": human_input.model_dump(mode="json"),
            "incident": incident,
            "statuses": {
                task.task_id: TaskStatus.PENDING.value for task in state["plan"].tasks
            },
            "artifacts": [],
            "completion_reasons": [],
            "action": SupervisorAction.EXECUTE_BATCH,
        }

    @staticmethod
    def _route_human_input(state: PlanningState) -> Literal["supervise", "finalize"]:
        return "finalize" if state["action"] is SupervisorAction.FAIL else "supervise"

    @staticmethod
    def _human_report(state: PlanningState) -> str:
        reasons = state.get("completion_reasons") or []
        detail = "；".join(reasons)
        return (
            "完成门禁未通过，需要人工补充信息，工作流已暂停。" + detail
            if detail
            else "当前无可执行任务，需要人工补充信息，工作流已暂停。"
        )

    @staticmethod
    def _thread_id(incident: IncidentContext) -> str:
        return f"planning:{incident.tenant_id}:{incident.incident_id}"

    @staticmethod
    def _config(thread_id: str) -> dict:
        return {
            "recursion_limit": 30,
            "configurable": {"thread_id": thread_id},
        }

    async def _require_tenant(self, thread_id: str, tenant_id: str | None) -> None:
        if tenant_id is None:
            return
        snapshot = await self.graph.aget_state(self._config(thread_id))
        if not snapshot.values:
            raise PlanValidationError(f"planning thread not found: {thread_id}")
        incident = snapshot.values.get("incident")
        actual = (
            incident.tenant_id
            if isinstance(incident, IncidentContext)
            else incident["tenant_id"]
        )
        if actual != tenant_id:
            raise PlanValidationError("planning thread belongs to another tenant")

    # 执行节点：并发执行就绪任务，记录成功/失败并保存制品。
    async def _execute_batch(self, state: PlanningState) -> dict:
        # 按任务 ID 建立计划任务索引，便于按 ID 取任务
        tasks = {task.task_id: task for task in state["plan"].tasks}
        # 按任务 ID 建立已有制品索引，供任务取用依赖制品
        artifacts_by_task = {artifact.task_id: artifact for artifact in state["artifacts"]}

        # 定义单个任务的执行逻辑：解析依赖制品并调用对应角色 Worker
        async def execute(task: TaskSpec) -> Artifact:
            # 从已产出的制品中挑选本任务依赖的制品列表
            dependencies = [
                artifacts_by_task[item]
                for item in task.dependencies
                if item in artifacts_by_task
            ]
            # 传入当前计划版本，确保 Replan 后产出的制品归属正确版本。
            return await self.workers.resolve(task.required_role).execute(
                state["incident"], task, dependencies, plan_version=state["plan"].version
            )

        # 取监督节点选出的就绪任务对象列表
        selected = [tasks[task_id] for task_id in state["ready_task_ids"]]
        # 并发执行全部就绪任务，单任务失败不阻断其他任务
        results = await asyncio.gather(
            *(execute(task) for task in selected), return_exceptions=True
        )
        # 复制当前状态表，避免污染图状态原始对象
        statuses = dict(state["statuses"])
        # 复制当前制品列表，在其上追加新制品
        artifacts = list(state["artifacts"])
        # 逐个任务按结果回写状态并收集制品
        for task, result in zip(selected, results, strict=True):
            # 任务以异常对象返回说明执行失败
            if isinstance(result, BaseException):
                # 把该任务状态标记为失败
                statuses[task.task_id] = TaskStatus.FAILED.value
                continue
            # 执行成功：把该任务状态标记为完成
            statuses[task.task_id] = TaskStatus.COMPLETED.value
            # 把产出制品追加进制品列表
            artifacts.append(result)
            # 把制品持久化到 Task/Artifact 存储
            self._save_artifact(state["incident"], state["plan"], result)
        # 返回更新后的状态表与制品列表供监督节点继续推进
        return {"statuses": statuses, "artifacts": artifacts}

    # 重规划节点：调用 Replanner 生成补丁并重新提交计划。
    async def _replan(self, state: PlanningState) -> dict:
        # 未注入 Replanner 时无法重规划，直接标记失败结束本线程。
        if not self.replanner:
            return {"action": SupervisorAction.FAIL}
        # 取出监督节点写入的重规划触发原因（内容触发时存在，失败触发时为空）。
        trigger = state.get("replan_trigger")
        trigger_model = ReplanTrigger.model_validate(trigger) if trigger else None
        # 调用 Replanner：基于当前事故、已提交计划与失败任务（或触发原因）生成计划补丁。
        patch = await self.replanner.replan(
            state["incident"],
            state["plan"],
            state.get("failed_task_ids", []),
            trigger=trigger_model,
        )
        # 把补丁应用到旧计划，提交为新版本计划。
        plan = self.controller.apply_patch(state["incident"], state["plan"], patch)
        # 重建状态表：新计划任务沿用旧状态，旧计划中不存在的新任务置为待执行。
        statuses = {
            task.task_id: state["statuses"].get(task.task_id, TaskStatus.PENDING.value)
            for task in plan.tasks
        }
        # 返回新计划、重建的状态表、自增的重规划次数，并清空已消费的触发原因。
        return {
            "plan": plan,
            "statuses": statuses,
            "replan_count": state.get("replan_count", 0) + 1,
            "replan_trigger": None,
        }

    # 收尾节点：根据最终动作生成状态与报告，完成时按需产出 DispatchProposal。
    async def _finalize(self, state: PlanningState) -> dict:
        # 监督节点路由到本节点时已确定最终动作，此处按动作写终态。
        action = state["action"]
        if action is SupervisorAction.COMPLETE:
            # 完成分支：标记终态为完成，并用已产出制品数生成报告。
            status = "completed"
            report = f"调查完成，共生成 {len(state['artifacts'])} 个结构化 Artifact。"
            # 默认无派单建议；仅当事故携带目标工单时才产出，否则不转交派单。
            proposal: DispatchProposal | None = None
            target = state["incident"].dispatch_target
            if target:
                # WritePolicy 约束：只产出只读派单建议，绝不直接写 Java/ES。
                proposal = build_dispatch_proposal(
                    state["incident"], state["plan"], state["artifacts"]
                )
            # 返回终态、报告与可选的派单建议，供 _result 组装对外结果。
            return {"final_status": status, "report": report, "proposal": proposal}
        # 失败分支（FAIL 或超限后终止）：统一标记失败并输出兜底报告。
        status = "failed"
        report = "调查未能在允许的恢复范围内完成。"
        return {"final_status": status, "report": report}

    # 将 Worker 制品持久化到 Task/Artifact 存储。
    def _save_artifact(
        self, incident: IncidentContext, plan: CommittedPlan, artifact: Artifact
    ) -> None:
        record = TaskArtifactRecord(
                tenant_id=incident.tenant_id,
                thread_id=incident.thread_id,
                plan_id=plan.plan_id,
                entity_id=artifact.artifact_id,
                kind="artifact",
                payload=artifact.model_dump(mode="json"),
                source=artifact.worker_id,
                trace_id=incident.trace_id,
            )
        existing = self.store.get(
            incident.tenant_id,
            incident.thread_id,
            plan.plan_id,
            artifact.artifact_id,
            "artifact",
        )
        self.store.put(record, expected_version=existing.version if existing else 0)
