# FlowFix 设备运维平台

本仓库是 Java 后端、Python Agent 和 Vue 前端的 monorepo。

```text
ep-system/
├── backend/   # Java 微服务与共享基础设施 Compose
├── agent/     # Python FlowFix Agent
└── frontend/  # Vue 3 + Vite 前端
```

## 本地运行顺序

### 1. 启动基础设施

```bash
cd backend
cp .env.example .env
docker compose up -d mysql redis rabbitmq nacos elasticsearch
docker compose ps
```

### 2. 启动 Java 服务

使用 JDK 17，在 IDEA 中依次启动 backend 下的 Java 服务；完整顺序和端口见
backend/LOCAL_DEVELOPMENT.md。

### 3. 启动 Agent

```bash
cd agent
cp .env.example .env
uv sync
uv run flowfix-agent serve --host 127.0.0.1 --port 8000
```

### 4. 启动前端

```bash
cd frontend
npm install
npm run dev
```

前端默认运行在 http://127.0.0.1:5173，Java Gateway 默认使用 8200，Agent 默认使用 8000。

## 配置安全

真实密码、API Key、Token 和模型连接文件只放在未提交的 `.env` 或系统环境变量中。
仓库中的 `.env.example` 只提供脱敏后的配置模板。
