# Adapters 与 Provider

当前包含知识源文件、Elasticsearch、Embedding、Reranker、LLM 生成器、生产 Planner 与单 Agent 调查决策端的具体实现。派单 Java HTTP Adapter 位于 `dispatch/adapters/java_http.py`；Redis（LangGraph Checkpoint/租约）、MySQL/SQLite（Memory）、RabbitMQ 异步派单和 MCP Streamable HTTP Client/Server 均由 Bootstrap/Lifespan 统一装配。

可被业务节点调用的外部实现统一视为 Provider Adapter：Local Python、Java HTTP 和 MCP 都实现稳定 capability 合同。Adapter 只转换协议、错误和领域模型，不拥有业务规则、权限或状态机。

Provider 的注册、选择、授权和执行已由 `tools/registry` / `tools/resolver` / `tools/policy` / `tools/gateway` 负责。动态发现 Provider 不会自动获得权限。详见 [TOOL_PLATFORM.md](../../../docs/TOOL_PLATFORM.md)。
