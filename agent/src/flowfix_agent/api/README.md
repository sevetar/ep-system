# API

FastAPI 传输层只做协议转换、可信身份上下文、Schema 校验和错误映射，不直接访问 Elasticsearch、模型、Java、Store 或 MCP。

生产环境必须配置 `API_AUTH_TOKEN`。可信网关通过 Bearer token 认证后，以
`X-Principal-Id`、`X-Tenant-Id`、`X-Principal-Permissions` 注入 Principal；请求正文不能
声明权威 permissions、reviewer 或 Dispatch tenant。线程恢复、重试、状态与历史查询都会
校验 Principal tenant 与 checkpoint 资源归属。

当前显式 API 调用 Knowledge、QA、Retrieval、Dispatch Runtime 与链三两个运行时（均已装配进容器）。派单 start/resume/retry/status/history 不能绕过状态图和 Tool Guard；`/health/ready` 检查当前必要依赖。

统一入口两条：`POST /v1/assistant/route` 由 Router 输出四种 RouteDecision（只分类、不执行业务）；`POST /v1/assistant/execute` 按路由结果同步编排三条链路。现有 `/v1/qa/query`、`/v1/dispatch/start`、`/v1/investigation/plan`、`/v1/investigation/run` 等显式 API 可直达对应链路，不重复调用 LLM Router，但必须保留链路内部校验。

Planning 人工补充使用 `POST /v1/planning/{thread_id}/resume`，Dispatch 审批使用
`POST /v1/dispatch/{thread_id}/resume`。普通 Dispatch 响应与 history 只返回稳定业务视图，
不暴露冻结 Skill、RequestContext 或完整 Worker 快照。

详见 [请求路由](../../../docs/others/REQUEST_ROUTING.md)。
