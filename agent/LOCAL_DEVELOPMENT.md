# 本地配置与运行

本文只记录本地配置和运行方式。真实 API Key、密码、Token、连接文件和生产地址只放在未提交的 `.env` 或系统环境变量中。

## 1. 准备配置

```bash
cd /path/to/ep-system/agent
cp .env.example .env
```

然后按本机环境修改 `.env`：

- `OPENAI_BASE_URL` 和 `OPENAI_API_KEY`：使用实际模型服务时填写；
- `MYSQL_PASSWORD`、`RABBITMQ_URL`：只在启用对应持久化/异步能力时填写；
- `JAVA_DISPATCH_BASE_URL`：默认指向本机 Java `service-device` 合同接口；
- `API_AUTH_TOKEN`、`MCP_AUTH_TOKEN`：生产或启用认证时必须使用独立随机值。

不要把 `.env`、模型连接 JSON、日志或评测输出提交到 Git。

## 2. 安装和离线验证

```bash
uv sync
uv run ruff check .
uv run pytest -q
bash scripts/demo.sh --quick
```

## 3. 启动共享基础设施

Java 项目的 Compose 文件位于相邻目录：

```bash
cd /path/to/ep-system/backend
cp .env.example .env
docker compose up -d mysql redis rabbitmq nacos elasticsearch
docker compose ps
```

## 4. 启动 Agent

```bash
cd /path/to/ep-system/agent
uv run flowfix-agent serve --host 127.0.0.1 --port 8000
```

默认 Java 派单合同地址是 `http://127.0.0.1:8085/internal/dispatch/v1`。共享网络或生产部署前，必须补充服务身份认证和安全的密钥管理。
