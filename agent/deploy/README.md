# Deploy

本目录只保存 Agent 镜像和部署配置，不维护本机基础组件 Compose。Elasticsearch、Redis、RabbitMQ 和 MySQL 复用 `../backend/compose.yaml`，本地运行方式详见 `../backend/LOCAL_DEVELOPMENT.md`。

当前仍部署一个模块化单体。Router、Tool Platform、Conversation/Task Store 和 Planning Runtime 默认在同一服务内装配；只有压测、隔离或独立扩缩容证据充分时才拆服务。MCP Provider 是外部适配边界，不改变三条业务链路。

多副本部署必须设置 `HA_MODE_ENABLED=true`、`STORE_BACKEND=mysql`、`REDIS_CHECKPOINT_ENABLED=true`、`RABBITMQ_ENABLED=true`，并给每个副本唯一 `INSTANCE_ID`。HTTP 流量可由上游负载均衡；Rabbit 队列使用竞争消费者。滚动发布前先确认新旧版本都兼容 `dispatch-request/v1` 与 `dispatch-outcome/v1`，再逐个替换副本。
