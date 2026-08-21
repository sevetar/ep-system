# Planning

六节点运行时：`plan / supervise / execute_batch / replan / request_human_input / finalize`。
Planner/Replanner 只提案，Validator 校验，Controller 提交版本，Supervisor 选择限定动作，
Worker 只返回 Artifact。CompletionGate 未通过时 `interrupt()` 真正暂停，Checkpointer 保存
执行位置；结构化 `PlanningHumanInput(action=retry|cancel)` 通过 resume API 恢复原线程。

- `adapters/planning_planner.py`：生产 **Planner**（`LangChainPlanningPlanner`），把事故上下文分解为通过 `PlanValidator` 校验的只读任务 DAG；只允许 `diagnosis / impact_safety / resource_planning` 三类角色，`allowed_capabilities` 固定为 `knowledge.search`，输出失败即 fail-closed。
- `adapters/investigation_decision.py`：生产 **单 Agent 调查决策端**（`LangChainInvestigationDecision`），有界约束能力并 fail-closed，驱动只读调查循环。
- `runtime.py`：`max_replans` 构造参数（默认 1）控制重规划预算，替换硬编码 `< 1`。
- 三个真实只读 Worker：`diagnosis`（根因假设）、`impact_safety`（影响与风险）、`resource_planning`（资源可用性），全部经 `knowledge.search` 只读检索证据，已注册进 `WorkerRegistry`。
- 在线入口：`POST /v1/investigation/plan`（多 Agent 规划）、
  `POST /v1/planning/{thread_id}/resume|status`、`POST /v1/investigation/run`（单 Agent
  只读调查），另经统一入口 `POST /v1/assistant/execute` 编排。
