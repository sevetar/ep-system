# FlowFix Web Console

FlowFix 设备运维平台前端，基于 Vue 3、Vite、Pinia 和 Element Plus。

当前前端同时连接：

- Java Gateway：登录、设备、工单、审批和消息；
- FlowFix Agent：服务就绪状态、知识问答和智能派单运行时。

## 本地启动

```bash
npm install
npm run dev
```

默认地址为 `http://127.0.0.1:5173`。开发服务器代理：

```text
/api       -> http://localhost:8200
/agent-api -> http://localhost:8001
/ws        -> ws://localhost:8200
```

Java Gateway、Agent 端口或部署拓扑不同时，复制 `.env.example` 为 `.env.local` 并覆盖对应 `VITE_*` 配置。

## 构建与检查

```bash
npm run build
npm audit --omit=dev
```

部署到非本机环境时，通过 `.env.local` 覆盖 `VITE_*` 地址，并确保 Java Gateway 与 Agent 已先启动。
