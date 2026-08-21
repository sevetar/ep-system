# Retrieval

知识读链路：Query Gate、BM25/Dense Recall、RRF、可选 Rerank、去重、阈值、类型配额、权限过滤和上下文预算。输出结构化 `EvidenceBundle`，不调用生成模型、不生成最终答案。

当前由 QA 直接通过 Port 调用。迁入公共 Tool Platform 后，现有服务成为 `knowledge.search` Provider：FAQ Workflow 确定性调用；Investigation Worker 只能在 Task capability view 授权时调用。两者复用实现和 scope 过滤，但不复用最终生成流程。

Query Rewrite 的会话语义属于 QA/Conversation 层；Retrieval 只接收原问题、改写问题和可信 scope，不拥有聊天历史。
