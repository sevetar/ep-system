from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

import pymysql


# MySQL 存储连接配置：地址、账号与目标库。
@dataclass(frozen=True)
class MySQLStoreConfig:
    host: str = "127.0.0.1"
    port: int = 3306
    user: str = "root"
    password: str | None = None
    database: str = "flowfix_agent"


# 时间戳列格式：不带时区的 UTC 时间文本（写入前由 aware datetime 格式化，读回时需按 UTC 解释）。
TS_FORMAT = "%Y-%m-%d %H:%M:%S"


# 确保目标数据库存在，便于首次启动自举建库。
def ensure_database(config: MySQLStoreConfig) -> None:
    connection = pymysql.connect(
        host=config.host,
        port=config.port,
        user=config.user,
        password=config.password or "",
        charset="utf8mb4",
        autocommit=True,
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"CREATE DATABASE IF NOT EXISTS `{config.database}` CHARACTER SET utf8mb4"
            )
    finally:
        connection.close()


# 打开 MySQL 连接：成功提交、异常回滚，退出时关闭连接。
@contextmanager
def mysql_session(config: MySQLStoreConfig) -> Iterator[pymysql.connections.Connection]:
    connection = pymysql.connect(
        host=config.host,
        port=config.port,
        user=config.user,
        password=config.password or "",
        database=config.database,
        charset="utf8mb4",
        autocommit=False,
    )
    try:
        yield connection
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()
