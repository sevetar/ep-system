from __future__ import annotations

import secrets

from redis.asyncio import Redis

_RELEASE_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('del', KEYS[1])
end
return 0
"""


class RedisLeaseManager:
    """跨进程短租约；只允许持有相同 token 的实例释放锁。"""

    def __init__(self, redis: Redis, *, prefix: str = "flowfix:lease:") -> None:
        self.redis = redis
        self.prefix = prefix

    async def acquire(self, resource: str, ttl_seconds: int) -> str | None:
        token = secrets.token_urlsafe(24)
        acquired = await self.redis.set(
            f"{self.prefix}{resource}", token, nx=True, ex=ttl_seconds
        )
        return token if acquired else None

    async def release(self, resource: str, token: str) -> bool:
        removed = await self.redis.eval(
            _RELEASE_SCRIPT, 1, f"{self.prefix}{resource}", token
        )
        return bool(removed)
