# Tests

测试按 `unit/component/contract/scenarios/fault_injection` 分层，镜像业务能力而不是第三方框架。

当前覆盖 Knowledge、Retrieval、QA、Dispatch、LLM 路由兜底、MCP Streamable HTTP、RabbitMQ 消费合同、Redis 租约和 HA 配置门禁，以及 Conversation/Task/Artifact/Planning 全链路。

优先使用 Fake Model、Fake Provider 和确定性 Clock；少量测试才访问真实 ES、模型或 Java。任何 Multi-Agent 场景都必须同时验证权限、预算、停止条件、Artifact 血缘和可重放性。
