# Dispatch 包结构与边界

`dispatch` 是 FlowFix 的自动派单限界上下文，承载三个已经验收的阶段：

- M3：给定冻结快照和冻结 Skill，确定性生成可解释、可重放的 `DispatchDecision`；
- M4：用固定 `StateGraph` 编排快照、决策、HITL、Fake 写入、结果核验和审计；
- M5 同步阶段：通过 `dispatch-contract/v1` Java HTTP Adapter 读取真实快照、提交派单命令并核验最终 outcome。

它不拥有 Java 工单真相，不把 Fake outcome 或 HTTP 200 表述为真实派单成功，也不允许 LLM 或 Skill 绕过硬门禁、权限、幂等和 expected version。

## 在三链路架构中的定位

Dispatch 是唯一真实业务写入安全区。统一 Router 可以把明确工单直接送入本链路；Incident Planning 只能提交 `DispatchProposal`，仍需重新经过本链路规则、HITL、幂等、`expectedVersion` 和 Java outcome。

计划迁入公共 Tool Platform 时保持现有 StateGraph 不变，只增加三个受控扩展点：

1. `pre_read_enrichment`：快照决策前补充只读证据；
2. `pre_write_validation`：写入前附加确定性校验；
3. `post_write_verification`：写后核验、通知或审计。

Hook 和 MCP Provider 必须预注册并通过公共 Policy/Gateway，不能获得额外权限或绕过主链。当前 MCP Server 不暴露写 Tool。详见 [公共 Tool Platform](../../../docs/others/TOOL_PLATFORM.md)。

## 当前目录

```text
dispatch/
├── __init__.py                 # 稳定公共入口，只导出高频领域类型和决策服务
├── README.md
├── domain/                     # 纯业务合同与不变量
│   ├── __init__.py
│   ├── errors.py               # DispatchError、非法状态迁移
│   ├── models.py               # Snapshot、Request、State、Decision、枚举
│   └── state_machine.py        # 显式允许迁移与终态保护
├── application/                # 确定性派单用例
│   ├── __init__.py
│   ├── errors.py               # 用例级幂等冲突
│   ├── ports.py                # Repository、Skill Registry、Trace 抽象端口
│   ├── rules.py                # 不可关闭的硬门禁和 Skill 资格规则
│   ├── scoring.py              # 归一化评分与稳定同分策略
│   └── service.py              # DispatchDecisionService
├── skills/                     # 声明式、版本化的 Agent 派单策略
│   ├── __init__.py
│   ├── errors.py
│   ├── manifest.py             # DispatchSkill、ToolPolicy、权重、风险阈值
│   ├── loader.py               # 只读取 JSON，不执行任意代码
│   ├── validator.py            # Schema、Tool contract 和 allowlist 校验
│   └── builtin/                # balanced 与 sla-first 固定版本
├── runtime/                    # M4 有状态 Agent 编排和 Tool Guard
│   ├── __init__.py
│   ├── errors.py
│   ├── models.py               # RequestContext、Command、Receipt、Outcome、审批
│   ├── ports.py                # 7 个 Typed Tool Port
│   ├── middleware.py           # 权限、超时、重试、熔断、预算、脱敏审计
│   └── graph.py                # StateGraph、interrupt/resume、Checkpoint 恢复
└── adapters/                   # 可替换的本地实现，不进入领域与用例层
    ├── __init__.py
    ├── decision_repository.py  # InMemory 决策幂等仓储
    ├── skill_registry.py       # 原子 JSON File Skill Registry
    ├── fake_tools.py           # M4 Fake Java/Tool Adapter
    └── java_http.py            # M5 dispatch-contract/v1 HTTP Adapter
```

根目录不再按 M3、M4 的实现时间堆放 `models.py`、`service.py`、`repository.py` 和 `runtime/fake.py`。新增代码必须先判断属于业务合同、用例、策略、运行时还是适配器。

## 依赖方向

```text
domain
  ^
  ├── skills
  ├── application ──> skills
  ├── runtime ──────> application + skills
  └── adapters ─────> domain/runtime contracts

evaluation/bootstrap/tests ──> dispatch public modules + adapters
```

硬性规则：

1. `domain` 只能依赖最小共享 `core`，不能导入 Skill、Runtime、Adapter、LangGraph 或外部 SDK；
2. `application` 只通过 Port 依赖仓储、Registry 和 Trace，不导入具体 Adapter；
3. `runtime` 可以编排 Application Service 和 Tool Port，但不能 new Java/Redis/RabbitMQ 客户端；
4. `adapters` 实现端口，可以依赖领域/运行时合同，反向依赖禁止；
5. `evaluation` 位于顶层包，依赖 `dispatch`，生产派单代码不得导入评测模块；
6. M5 的真实 Java 实现位于 `dispatch.adapters` 并由 Bootstrap 装配；后续 RabbitMQ/Redis 也只能经 Adapter/Bootstrap 接入，不回填进 `domain` 或 `runtime.graph`。

## M3 决策数据流

```text
DispatchRequest + WorkOrderSnapshot + WorkerSnapshot[]
  -> DispatchDecisionService.prepare
  -> 冻结输入、Skill 版本和内容 hash
  -> validate_work_order
  -> filter_workers
  -> score_candidates
  -> risk thresholds / deterministic tie-break
  -> DispatchDecision
  -> save_if_absent + Trace
```

结果语义：

- `REJECTED`：工单状态、租户或已派单等硬条件不合法；
- `MANUAL`：无候选或风险阈值要求人工处理；
- `ASSIGN`：产生了合法的离线派单决策；
- `external_execution_status=not_started`：不代表 Java 写入成功。

## M4 Runtime 数据流

```text
freeze_skill
  -> load_snapshot
  -> decide
  -> [auto] execute -> verify -> audit
  -> [risk] mark_approval -> interrupt
                         -> Command(resume)
                         -> approve: execute -> verify -> audit
                         -> deny: audit
```

`DispatchToolGateway` 在 Adapter 调用前同时检查：

- 系统 Tool allowlist；
- 冻结 Skill 的 `dispatch-tools/v1` read/write policy；
- Request Context 的 read/write/audit permission；
- tenant、event id、deadline 和调用预算；
- 写命令的 idempotency key 与 expected version；
- 有界 Retry、Circuit Breaker、结构化审计与 Secret Redaction。

Skill 只能收紧工具范围，不能扩大系统权限。人工审批也只能选择冻结候选集中的维修员。
单次 Tool timeout、自动执行 deadline 与人工审批 TTL 是三个独立概念；暂停恢复时先校验
`approval_expires_at`，再通过 `Command(update=..., resume=...)` 重新签发短执行 deadline，
不会沿用暂停前已过期的 deadline。API 权限与 reviewer 来自可信 Principal。

## Adapter 边界

当前 `adapters/` 同时包含本地阶段实现和真实 Java 边界：

- `InMemoryDispatchDecisionRepository`：证明事件级幂等，不具备跨进程持久性；
- `FileDispatchSkillRegistry`：证明版本注册、激活和回滚，不是多实例配置中心；
- `FakeDispatchToolAdapter`：模拟 expected version、幂等写、响应丢失和最终状态核验，不代表真实 Java 指标。
- `JavaDispatchHttpAdapter`：映射 `dispatch-contract/v1` 的快照、候选、命令、receipt 和 outcome，并实现本地幂等审计。

M5 同步 HTTP 联调已验证真实 `ACCEPTED -> ASSIGNED`、expectedVersion、重放和幂等键冲突；Java 仍拥有工单最终状态。Redis 只承担后续短期幂等/锁/限流，RabbitMQ 只承担后续事件投递和 ACK/DLQ。真实 Adapter 必须实现现有 Port，不得改变领域层依赖方向。

## 公共导入

调用方优先使用稳定入口：

```python
from flowfix_agent.dispatch import (
    DispatchDecisionService,
    DispatchRequest,
    WorkerSnapshot,
    WorkOrderSnapshot,
)
```

装配层和测试需要具体实现时显式导入：

```python
from flowfix_agent.dispatch.adapters import (
    FakeDispatchToolAdapter,
    FileDispatchSkillRegistry,
    InMemoryDispatchDecisionRepository,
)
from flowfix_agent.dispatch.runtime import DispatchAgentRuntime, DispatchToolGateway
```

不要重新建立 `dispatch.models`、`dispatch.service` 等兼容转发文件；内部调用应通过新包路径或根公共入口，防止结构再次双轨化。

## 验证命令

```bash
uv run ruff check src tests

uv run flowfix-agent evaluate-dispatch \
  --dataset evals/datasets/dispatch_m3.jsonl \
  --output evals/reports/dispatch-m3-evaluation.json

LANGGRAPH_STRICT_MSGPACK=true uv run flowfix-agent evaluate-runtime \
  --dataset evals/datasets/dispatch_m4.jsonl \
  --output evals/reports/dispatch-m4-runtime-evaluation.json
```

M3 报告验证策略正确性、确定性、解释完整性和版本生命周期；M4 报告验证暂停恢复、Checkpoint 恢复、Tool Guard 和重复副作用。两类报告都只使用合成数据。
