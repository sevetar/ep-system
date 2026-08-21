# Bootstrap

应用生命周期与唯一依赖装配入口。当前创建配置、Elasticsearch、模型 Provider、Java dispatch httpx client，并装配知识写链路、Retrieval、QA 和同步派单 Runtime。

未来也只有这里可以：

- 选择 Tool Provider 并注册到 Registry；
- 装配 Resolver、Policy 和 Gateway；
- 选择 Conversation/Task Store Adapter；
- 装配 Router、Investigation 和六节点 Planning Runtime（含可恢复人工输入）；
- 创建并关闭 MCP/Redis/RabbitMQ 等外部 Client，管理 Rabbit 消费者与 MCP Session Manager 生命周期。

业务模块不得读取全局可变单例、创建具体外部 Client，或根据环境自行绕过 Resolver。
