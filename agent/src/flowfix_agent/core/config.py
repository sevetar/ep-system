from __future__ import annotations

import json
import os
import socket
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from flowfix_agent.core.errors import ConfigurationError


# 保存 OpenAI 兼容模型服务的地址与密钥。
class ModelCredentials(BaseSettings):
    base_url: str
    api_key: SecretStr


# 集中加载并校验应用、检索、模型与运行目录配置。
class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "flowfix-agent"
    app_env: Literal["local", "test", "production"] = "local"
    log_level: str = "INFO"
    # 生产环境必须配置的入站 API 共享令牌；由可信网关连同 Principal 头注入。
    api_auth_token: SecretStr | None = None

    elasticsearch_url: str = "http://localhost:9200"
    elasticsearch_index: str = "flowfix-knowledge-v1"
    knowledge_root: Path = Path("../backend/docs")
    runtime_dir: Path = Path(".runtime")
    conversation_ttl_hours: int = Field(default=24, ge=1, le=720)
    conversation_recent_limit: int = Field(default=8, ge=2, le=50)

    openai_base_url: str = "https://api.example.com/v1"
    openai_api_key: SecretStr | None = None
    model_connection_file: Path | None = None
    chat_model: str = "qwen3.5-flash"
    embedding_model: str = "qwen3-embedding-0.6b"
    embedding_dimensions: int = Field(default=1024, ge=8, le=4096)
    rerank_model: str = "qwen3-reranker-0.6b"
    rerank_enabled: bool = True
    router_llm_fallback_enabled: bool = True

    chunk_size: int = Field(default=900, ge=200, le=4000)
    chunk_overlap: int = Field(default=120, ge=0, le=1000)
    embedding_batch_size: int = Field(default=16, ge=1, le=128)
    bm25_top_k: int = Field(default=20, ge=1, le=100)
    vector_top_k: int = Field(default=20, ge=1, le=100)
    final_top_k: int = Field(default=6, ge=1, le=30)
    rrf_k: int = Field(default=60, ge=1, le=1000)
    evidence_token_budget: int = Field(default=3000, ge=256, le=16000)
    vector_min_score: float = Field(default=0.60, ge=0.0, le=2.0)
    rerank_min_score: float = Field(default=0.20, ge=0.0, le=1.0)
    model_timeout_seconds: float = Field(default=45.0, gt=0, le=300)
    # Diagnosis Worker 单次执行的最大检索次数，防止超出工具调用预算。
    diagnosis_max_queries: int = Field(default=3, ge=1, le=10)
    # ImpactSafety Worker 单次执行的最大检索次数，防止超出工具调用预算。
    impact_safety_max_queries: int = Field(default=3, ge=1, le=10)
    # ResourcePlanning Worker 单次执行的最大检索次数，防止超出工具调用预算。
    resource_planning_max_queries: int = Field(default=3, ge=1, le=10)
    # 规划控制面允许的最大重规划次数，超过后失败任务直接 FAIL。
    max_replans: int = Field(default=1, ge=0, le=3)
    # 单 Agent 只读调查的最大步数，防止调查循环无界执行。
    investigation_max_steps: int = Field(default=6, ge=1, le=12)
    # 调查决策是否走原生 function calling 分支；默认关闭，保持 text-json 兼容路径。
    investigation_native_tools: bool = False
    # 统一入口中简单调查的更低步骤预算；复杂任务才升级到多 Agent Planning。
    assistant_simple_investigation_max_steps: int = Field(default=4, ge=1, le=12)
    # 完成门禁必须覆盖的 Worker 角色；为空时按成功标准关键词映射推断。
    completion_required_roles: list[str] = Field(default_factory=list)

    java_dispatch_base_url: str = "http://localhost:8085/internal/dispatch/v1"
    java_dispatch_timeout_seconds: float = Field(default=3.0, gt=0, le=30)
    dispatch_tool_timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    dispatch_execution_timeout_seconds: int = Field(default=60, ge=5, le=300)
    dispatch_approval_ttl_seconds: int = Field(default=3600, ge=60, le=86400)

    # Memory 存储：store_backend 决定 Conversation/Task-Artifact 使用 MySQL 还是 SQLite。
    store_backend: Literal["sqlite", "mysql"] = "sqlite"
    mysql_host: str = "127.0.0.1"
    mysql_port: int = Field(default=3306, ge=1, le=65535)
    mysql_user: str = "root"
    mysql_password: SecretStr | None = None
    mysql_database: str = "flowfix_agent"
    # LangGraph Checkpoint 复用 Java 侧 Redis（6379，redis-stack 提供 RediSearch）；
    # 默认开启，使 HITL 暂停/恢复跨进程持久化；本地无 Redis 时用 .env 关闭。
    # 仅当 redis_checkpoint_enabled=True 且 redis_url 非空时才启用 Redis Checkpoint，
    # 否则退化为 InMemorySaver。
    redis_url: str | None = "redis://127.0.0.1:6379"
    redis_checkpoint_enabled: bool = True

    # MCP 仅暴露公共 Gateway 中预注册的只读能力。生产启用时必须使用独立令牌。
    mcp_server_enabled: bool = False
    mcp_auth_token: SecretStr | None = None
    mcp_allowed_tenants: set[str] = Field(default_factory=lambda: {"public"})
    mcp_remote_url: str | None = None
    mcp_remote_token: SecretStr | None = None
    mcp_remote_capabilities: dict[str, str] = Field(default_factory=dict)
    mcp_timeout_seconds: float = Field(default=10.0, gt=0, le=60)

    # RabbitMQ 异步派单链路及多实例运行参数；默认关闭以保持纯本地开发轻量。
    rabbitmq_enabled: bool = False
    # 工单完成后自动沉淀维修案例；可与自动派单消费者独立启用。
    work_order_knowledge_enabled: bool = False
    rabbitmq_url: str = "amqp://guest:guest@127.0.0.1:5672/"
    rabbitmq_retry_delay_ms: int = Field(default=5000, ge=100, le=300_000)
    rabbitmq_max_retries: int = Field(default=3, ge=0, le=20)
    ha_mode_enabled: bool = False
    instance_id: str = Field(
        default_factory=lambda: f"{socket.gethostname()}-{os.getpid()}"
    )

    # 校验分块重叠长度必须严格小于分块长度。
    @model_validator(mode="after")
    def validate_chunking(self) -> Settings:
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("CHUNK_OVERLAP must be smaller than CHUNK_SIZE")
        if self.app_env == "production" and not self.api_auth_token:
            raise ValueError("API_AUTH_TOKEN is required in production")
        if self.app_env == "production" and self.mcp_server_enabled and not self.mcp_auth_token:
            raise ValueError("MCP_AUTH_TOKEN is required when MCP is enabled in production")
        if self.mcp_server_enabled and not self.mcp_allowed_tenants:
            raise ValueError("MCP_ALLOWED_TENANTS must not be empty when MCP is enabled")
        if self.ha_mode_enabled:
            if self.store_backend != "mysql":
                raise ValueError("HA_MODE_ENABLED requires STORE_BACKEND=mysql")
            if not self.redis_checkpoint_enabled or not self.redis_url:
                raise ValueError("HA_MODE_ENABLED requires Redis checkpointing")
            if not self.rabbitmq_enabled:
                raise ValueError("HA_MODE_ENABLED requires RABBITMQ_ENABLED=true")
        return self

    # 返回展开用户目录并转换为绝对路径的知识根目录。
    @property
    def resolved_knowledge_root(self) -> Path:
        return self.knowledge_root.expanduser().resolve()

    # 返回展开用户目录并转换为绝对路径的运行时目录。
    @property
    def resolved_runtime_dir(self) -> Path:
        return self.runtime_dir.expanduser().resolve()

    # 从环境变量或本地连接文件解析并校验模型凭据。
    def model_credentials(self) -> ModelCredentials:
        if self.openai_api_key:
            return ModelCredentials(
                base_url=self._normalize_base_url(self.openai_base_url),
                api_key=self.openai_api_key,
            )
        if not self.model_connection_file:
            raise ConfigurationError(
                "Set OPENAI_API_KEY or MODEL_CONNECTION_FILE before using model-backed features"
            )
        path = self.model_connection_file.expanduser().resolve()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            api_key = payload["key"]
            base_url = payload["url"]
        except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
            raise ConfigurationError(f"Invalid model connection file: {path}") from exc
        if not isinstance(api_key, str) or not api_key:
            raise ConfigurationError("Model connection file contains an empty key")
        if not isinstance(base_url, str) or not base_url.startswith("https://"):
            raise ConfigurationError("Model connection file URL must use HTTPS")
        return ModelCredentials(
            base_url=self._normalize_base_url(base_url),
            api_key=SecretStr(api_key),
        )

    # 规范化模型服务地址，保证其以 /v1 结尾。
    @staticmethod
    def _normalize_base_url(value: str) -> str:
        base_url = value.rstrip("/")
        return base_url if base_url.endswith("/v1") else f"{base_url}/v1"


# 创建并缓存进程级应用配置。
@lru_cache
def get_settings() -> Settings:
    return Settings()
