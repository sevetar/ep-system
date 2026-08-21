# Knowledge

知识写链路与生命周期所有者：知识源登记、不可变快照、解析、规范化、Chunk、元数据/权限、版本、索引提交和失效。它产出可重建 Search Projection，不回答用户问题，也不保存 Conversation/Task Memory。

Knowledge 同时服务两条只读链路：FAQ 通过固定 RAG 获取 EvidenceBundle；Investigation 未来通过获准的 `knowledge.search` capability 获取结构化证据。调查不得调用完整 FAQ 文本答案作为事实来源。

Elasticsearch 是 Search Projection，不是 Agent、原始知识真相或工单交易状态。
