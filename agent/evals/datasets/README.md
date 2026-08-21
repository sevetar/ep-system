# Evaluation Datasets

保存人工审阅且脱敏的固定评测集：Retrieval/QA、Dispatch、Router、FAQ 多轮、Tool Selection、Planning/Replan、知识闭环和故障恢复。每条场景必须标注预期路由、关键证据/任务、允许的 capability、停止原因和安全失败；不得包含生产隐私或密钥。固定集用于当前提交的回归和本地量化，不等同于隐藏生产测试集。

## 2026-08-15 benchmark v1

- `flowfix_l2.jsonl`：50 条真实知识库标注，包含 32 条单文档、10 条多文档和 8 条不可回答问题。Runner 输出整体及切片级检索/QA 指标。
- `router_phase_a.jsonl`：50 条四分类固定集，每类 12～13 条；Runner 输出 Accuracy、Macro-F1、各类 Precision/Recall/F1、混淆矩阵和危险误路由数。
- `knowledge_e2e_v1.jsonl`：K01～K10 的 E2E 输入与预期清单；工单和设备 ID 中的 `{{RUN_ID}}` 必须在发送前替换，`event_id/completed_at/trace_id` 由真实执行链路生成并记录。它是桌面量化测试包 L6 的用例真相，不由离线 runner 冒充真实 RabbitMQ/模型/ES/Java 结果。

数据质量由 `tests/unit/test_evaluation_datasets.py` 约束：样本 ID 唯一、切片规模、引用源存在、答案关键词可在标注源找到、Router 分布，以及 K01～K08 与当前质量门禁规则一致。

Phase A 新增：`router_phase_a.jsonl`、`faq_conversation_phase_a.jsonl`、`tool_selection_phase_a.jsonl` 和 `planning_mvp.jsonl`。

- ✅ `router_phase_a.jsonl`：由 Router 固定集评测覆盖。
- ⬜ `faq_conversation_phase_a.jsonl`、⬜ `tool_selection_phase_a.jsonl`：当前由单元/场景测试覆盖，无独立 runner，不新建 runner。
- ⬜ `planning_mvp.jsonl`：在五节点 Runtime 已闭环，Golden 与公平评测使用独立数据集，本集暂无独立 runner。
