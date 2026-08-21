# Routing

`RequestRouter` 保留纯规则 `route()` 与在线 `route_async()`。在线路径只在规则无法判断时调用 `LLMRouteClassifier`，结构化结果经 Pydantic 校验；超时、异常或非法输出安全退化为 `NEEDS_CLARIFICATION`。Router 不执行 Tool、不补造实体，也不拥有写权限。

统一自然语言入口的确定性优先路由。Router 只识别意图并提取通用实体，不判断各业务链路
的必填字段，也不持有 Tool 权限。只有意图不明确时才返回 `NEEDS_CLARIFICATION`；派单的
`work_order_id` 和调查的 `device_id` 分别由对应链路校验。未来只有规则无法判断的样本才接
结构化 LLM classifier。
