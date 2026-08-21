# 本地开发环境

项目本地运行需要 MySQL、Redis、RabbitMQ、Nacos 和 Elasticsearch。根目录的
`compose.yaml` 使用环境变量读取本地密码；不要把真实凭据写入 Git、文档或命令历史。
该 Compose stack 同时是本仓库 `agent` 项目的本机基础组件来源；不要再为 Agent
单独启动 Elasticsearch、Redis 或 RabbitMQ。

## 启动基础组件

如果终端可以直接使用 Docker：

```bash
cp .env.example .env
# 按需修改 .env 中的本地密码；.env 已被 Git 忽略。
docker compose up -d
docker compose ps
```

从终端启动 Java 服务前，可将同一份本地配置导入当前 shell：

```bash
set -a
source .env
set +a
```

如果 macOS 中 Docker Desktop 已启动、但终端找不到 `docker`：

```bash
PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH" docker compose up -d
PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH" docker compose ps
```

组件地址：

| 组件 | 地址 | 账号 |
| --- | --- | --- |
| MySQL | `localhost:3308` | `root` / `MYSQL_ROOT_PASSWORD` |
| Redis | `localhost:6379` | 本地默认无密码 |
| RabbitMQ | `localhost:5672` | `RABBITMQ_USER` / `RABBITMQ_PASSWORD` |
| RabbitMQ 控制台 | <http://localhost:15672> | 使用同一组 RabbitMQ 环境变量 |
| Nacos 控制台 | <http://localhost:8848/nacos> | 未开启鉴权 |
| Elasticsearch | <http://localhost:9200> | 未开启鉴权 |

`agent` 当前在该 Elasticsearch 中使用独立索引 `flowfix-knowledge-v1`。后续接入
Redis/RabbitMQ 时也复用本表端口和账号，但业务 key 前缀、队列、exchange 与 Java
项目分别命名，避免共享实例时发生逻辑冲突。

MySQL 第一次创建数据卷时会自动初始化 `users`、`devices` 两个数据库。修改初始化
SQL 后不会自动重放；开发环境需要全新初始化时，应先确认没有要保留的数据，再删除
本项目的 MySQL 数据卷。

## IDEA 启动顺序

基础组件健康后，依次启动：

1. `ServiceAclApplication`
2. `ServiceProductApplication`
3. `ServiceApprovalApplication`
4. `ServiceMessageApplication`
5. `ServiceSearchApplication`
6. `ServiceGatewayApplication`

项目要求 JDK 17。IDEA 的 Project SDK、Maven Runner JRE 和各 Run Configuration
都应使用 JDK 17。

## Java-Agent 同步联调

`service-device` 的派单合同接口不经过 Gateway，供本机运行的 `agent`
直接联调；本地个人项目不额外配置服务间共享密钥。

服务启动后可先验证合同健康状态：

```bash
curl http://localhost:8085/internal/dispatch/v1/health
```

预期返回 `status=UP` 和 `contractVersion=dispatch-contract/v1`。完整联调使用的固定
数据位于 `docker/mysql/demo/dispatch-v1-seed.sql`；已有 MySQL volume 不会自动执行
该脚本，需要按需手动导入。接口、场景和验收结果见
[`docs/JAVA_PRE_INTEGRATION_CHANGELOG.md`](docs/JAVA_PRE_INTEGRATION_CHANGELOG.md)。
