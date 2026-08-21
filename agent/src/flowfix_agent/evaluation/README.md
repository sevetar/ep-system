# Evaluation

生产模块之外的离线评测编排。当前包含通用 JSONL/报告工具、QA、Dispatch Decision 和 Dispatch Runtime 评测；依赖方向固定为 `evaluation -> production modules`。

计划增加 Router、Conversation、Tool Selection、Planning/Replan 和 Single/Multi-Agent 公平对照。生产代码不得反向导入本模块；评测数据、指标和报告不能成为线上状态真相。

数据集与运行说明见 [evals/README.md](../../../evals/README.md)。
