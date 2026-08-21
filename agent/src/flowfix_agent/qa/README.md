# QA

Knowledge QA 是固定 Workflow，不进入 Planner、Multi-Agent 或开放式 ReAct。

## 当前状态

✅ 已实现多轮 `Prepare -> Execute -> Validate -> Commit`：检索 EvidenceBundle、单次受约束生成、引用编号校验、拒答、SQLite Conversation Memory 与 Trace。当前引用校验不能夸大为语义 Groundedness。

## 多轮链路

```text
Load Conversation -> Query Rewrite -> Prepare/Retrieve
-> Generate/Abstain -> Citation Validate
-> Update Conversation -> Optional Finalize
```

Conversation Memory 已实现，namespace 是 `tenant + user + thread`，状态只包含 Recent、Rolling Summary、Entity Slots、Current Topic 和结束总结。它不能改变固定 RAG 路径，也不能未经确认写长期 Profile。

检索通过公共 `knowledge.search` capability 确定性触发；“确定性”表示模型不选择是否调用 Tool，不表示底层 Provider 不可替换。

详见 [Conversation Memory](../../../docs/CONVERSATION_MEMORY.md) 和 [知识链路](../../../docs/KNOWLEDGE_CHAIN.md)。
