# Observability

结构化日志、Trace、Metrics、审计和回放的统一约定。当前至少区分 Ingestion、Retrieval、QA 和 Dispatch；Trace 失败不能改变核心业务结果，但必须产生可见告警。

目标血缘：

```text
trace_id -> route -> thread/incident -> plan/version -> task -> worker
-> capability/provider/tool_call -> artifact -> dispatch -> Java outcome
```

Conversation Trace 记录原问题、改写引用、摘要版本和窗口决策，但不记录敏感原文或完整思维过程。Planning Trace 记录结构化状态、动作、版本和停止原因。Secret、敏感字段和 Tool Observation 必须脱敏/裁剪。
