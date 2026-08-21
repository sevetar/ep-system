# 应用源码边界

`main.py` 是应用入口，`bootstrap/` 是唯一具体依赖装配入口。

## 当前已实现

- Knowledge QA：`knowledge -> retrieval -> qa`；
- Controlled Dispatch：`dispatch.domain <- skills/application <- runtime`，Provider 位于 `dispatch.adapters`；
- 横切能力：`api/core/adapters/bootstrap/observability/evaluation`。

## 计划新增

```text
routing          统一入口，只选择链路
tools            Registry/Resolver/Policy/Gateway/Provider
memory           Conversation与Task/Artifact Store
investigation    只读Function Calling与Bounded ReAct
planning         plan/supervise/execute_batch/replan/finalize
```

这些目录在实际开始实现合同和测试时创建。不能用空包表示能力完成。

## 依赖原则

- FAQ 固定 RAG，Conversation Memory 只负责多轮理解；
- Dispatch 固定 StateGraph，扩展只能进入受控 Hook；
- Investigation Worker 只读，只返回 Artifact；
- 三条链路通过公共 capability 复用 Provider，但不合并执行策略；
- Evaluation 依赖生产模块，生产模块不得反向导入 Evaluation；
- 具体 ES、模型、Java、Store、MCP/RabbitMQ/Redis Client 只能由 Bootstrap 创建。

完整设计见 [项目架构](../../docs/ARCHITECTURE.md) 和 [模块边界](../../docs/most_used/MODULES.md)。
