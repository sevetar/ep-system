import json

import pytest
from pydantic import SecretStr
from pydantic_core import ValidationError

from flowfix_agent.core.config import Settings


# 验证可以从连接文件加载模型配置且不会暴露密钥明文。
def test_connection_file_is_loaded_without_exposing_key(tmp_path):
    connection_file = tmp_path / "connection.json"
    connection_file.write_text(
        json.dumps({"key": "secret-value", "url": "https://provider.example"}),
        encoding="utf-8",
    )
    settings = Settings(
        _env_file=None,
        openai_api_key=None,
        model_connection_file=connection_file,
    )

    credentials = settings.model_credentials()

    assert credentials.base_url == "https://provider.example/v1"
    assert credentials.api_key.get_secret_value() == "secret-value"
    assert "secret-value" not in repr(credentials)


# 验证显式 API Key 的优先级高于本地连接文件。
def test_explicit_api_key_takes_precedence(tmp_path):
    settings = Settings(
        _env_file=None,
        openai_api_key=SecretStr("explicit"),
        openai_base_url="https://provider.example/v1/",
        model_connection_file=tmp_path / "missing.json",
    )

    credentials = settings.model_credentials()

    assert credentials.base_url == "https://provider.example/v1"
    assert credentials.api_key.get_secret_value() == "explicit"


def test_production_requires_api_auth_token() -> None:
    with pytest.raises(ValidationError, match="API_AUTH_TOKEN"):
        Settings(_env_file=None, app_env="production", api_auth_token=None)


def test_ha_mode_requires_external_shared_state() -> None:
    with pytest.raises(ValidationError, match="STORE_BACKEND=mysql"):
        Settings(_env_file=None, ha_mode_enabled=True, store_backend="sqlite")


def test_ha_mode_accepts_mysql_redis_and_rabbitmq() -> None:
    settings = Settings(
        _env_file=None,
        ha_mode_enabled=True,
        store_backend="mysql",
        redis_checkpoint_enabled=True,
        redis_url="redis://redis:6379",
        rabbitmq_enabled=True,
    )

    assert settings.ha_mode_enabled is True
