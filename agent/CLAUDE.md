# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目定位

FlowFix Agent 是设备运维 Java 微服务（`../backend`）旁边的 Python Agent 服务，架构是「统一入口、三条专业链路、共享工程底座」，不是万能 Agent。

| 链路 | 职责 | 执行模式 | 状态 |
| --- | --- | --- | --- |
| Knowledge QA | 回答手册/SOP/历史知识 | 固定 RAG Workflow + SQLite 多轮会话 | ✅ |
| Controlled Dispatch | 对明确工单安全派单 | 固定 StateGraph + HITL，Java 同步闭环 | ✅（决策仓库持久化 + Redis Checkpoint 默认开启） |
| Incident Investigation & Planning | 调查故障并制定处置计划 | Plan-and-Execute + 只读 Multi-Agent + HITL | ✅（Planning interrupt/resume + 在线端点） |

已补齐工程基线：LLM 路由兜底、MCP Server/Client、RabbitMQ 异步链路与多实例共享状态。容量、故障切换时延、集中指标和长期 SLO 尚未实测，因此不得描述为“生产级高可用”。

包根在 `src/flowfix_agent/`；代码注释、文档和 README 均为中文。所有未完成能力在代码/测试/评测完成前必须标记 ⬜，不得写成已实现。

## 常用命令

依赖与质量（uv，Python 3.12，`.venv` 已存在）：

```bash
uv sync                                   # 安装/同步依赖
uv run ruff check .                       # lint（line-length 100）
uv run pytest -q                          # 全量测试
uv run pytest tests/unit/test_routing.py -q        # 单文件测试
```

运行与评测（离线门禁，全部通过 `uv run flowfix-agent` 子命令）：

```bash
uv run flowfix-agent ingest                                              # 摄取 Markdown 知识
uv run flowfix-agent query '为什么使用 Redisson 锁后仍可能重复抢单？'
uv run flowfix-agent serve                                               # FastAPI :8000
uv run flowfix-agent evaluate --with-qa                                  # L2 检索/QA
uv run flowfix-agent evaluate-dispatch                                   # M3 派单
LANGGRAPH_STRICT_MSGPACK=true uv run flowfix-agent evaluate-runtime      # M4 StateGraph/HITL/Tool Guard
uv run flowfix-agent evaluate-foundation                                 # Phase A Router
```

评测数据集在 `evals/datasets/`，报告输出到 `evals/reports/`（已 gitignore）。评测命令含门禁，失败会以非零码退出。

测试分层镜像业务能力：`tests/unit`（纯单元）、`tests/component`（真实 ES）、`tests/contract`（Java HTTP 契约）、`tests/scenarios`（端到端场景）、`tests/fault_injection`。pytest 标记：`integration`（真实基础设施）、`live`（外部模型调用），`asyncio_mode=auto`。优先用 Fake Model/Fake Provider/确定性 Clock，少量测试才访问真实 ES/模型/Java。

## 外部依赖与配置

- **Elasticsearch**：由 `../backend/compose.yaml` 提供（`docker compose up -d elasticsearch`），Agent 用独立索引 `flowfix-knowledge-v1`。
- **模型凭据**：`OPENAI_API_KEY` 或未提交的 `MODEL_CONNECTION_FILE`（NewAPI JSON，含 `key`/`url`）。两者都不能写入代码、文档或 Trace。
- **Java 派单**：默认直连本机 `http://localhost:8085/internal/dispatch/v1`，本地联调不额外配置共享密钥；真实工单状态始终由 Java 所有。
- 配置集中在 `core/config.py` 的 `Settings`（pydantic-settings 读 `.env`），示例见 `.env.example`。
- 入站 API：生产环境必须配置 `API_AUTH_TOKEN`；tenant/user/permissions/reviewer 仅来自认证后的 Principal，不得取请求正文。

## 架构

### 入口与装配

- `api/` 只负责协议、Schema、错误映射（统一 422）；不得直接访问 ES/模型/Java/Provider。
- `bootstrap/container.py` 是**唯一**创建具体 Client/Store/Provider 的地方（`AppContainer` + `build_container`），负责生命周期。业务模块只依赖 Port/合同。
- `cli.py`（Typer）是离线入口；`main.py` 创建 FastAPI app。

### 三条链路

1. **Knowledge QA**：`knowledge`（摄取/版本）→ `retrieval`（BM25/Dense、RRF、可选 Rerank、证据选择）→ `qa`（固定 RAG + 引用校验 + 拒答）。QA 不使用 Planner/Multi-Agent/开放 ReAct，只固定调用 `knowledge.search`。
2. **Controlled Dispatch**：依赖方向 `dispatch.domain ← dispatch.skills/application ← dispatch.runtime`，`dispatch.adapters` 实现 ports。`runtime/graph.py` 是固定 LangGraph（HITL、Typed Tool Guard）；版本化 Skill 声明在 `dispatch/skills/builtin/`（balanced/sla-first）。扩展只允许三类 Hook：read enrichment、pre-write validation、post-write verification/audit，不能修改主状态图的安全不变量。
3. **Investigation & Planning**：`investigation/loop.py` 是有界只读 Tool Loop；`planning/runtime.py` 是六节点控制面 `plan/supervise/execute_batch/replan/request_human_input/finalize`，使用 Checkpointer + interrupt/resume。Worker 不写业务；`finalize` 只能输出报告或 `DispatchProposal`，真实写入仍由 Dispatch 完成。

### 公共底座

- `routing/`：确定性优先 Router，输出 `KNOWLEDGE_QA / DIRECT_DISPATCH / INCIDENT_INVESTIGATION / NEEDS_CLARIFICATION`；只识别意图，不校验业务必填字段，也无 Tool 权限。派单与调查链路分别校验 `work_order_id`、`device_id`。
- `tools/`：公共 Tool Platform，`registry → resolver → policy → gateway → providers`。MCP 只是 Provider Adapter，动态发现 ≠ 动态授权；Policy/Gateway 统一参数、tenant、预算、超时、重试、脱敏、审计。
- `memory/`：SQLite Conversation Store 与 Task/Artifact Store。Memory 保存结构化状态，不保存模型完整思维过程。
- `adapters/`：把 ES/模型/Java/未来 MCP 等转换为领域合同，不含业务规则。
- `observability/`：JSONL Trace。`evaluation/` 依赖生产模块，生产模块不得反向导入 evaluation。

## 评审要点（核心不变量）

1. Router 只选链路，不执行 Tool 或业务写入，也不承担链路业务字段完整性校验。
2. FAQ 保持固定 RAG；Dispatch 保持确定性写入安全区；只有 Investigation 使用动态 Planning。
3. 三条链路共享 capability/合同，但不合并执行策略。
4. 具体 ES/模型/Java/Store/Provider 只能由 Bootstrap 创建；业务代码用 Port。
5. 一切 ⬜ 能力在代码、测试和评测完成前不得描述为已实现。
