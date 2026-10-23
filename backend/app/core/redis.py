from __future__ import annotations

import logging

import redis.asyncio as aioredis
from redis.exceptions import RedisError

log = logging.getLogger("andripa.redis")


class RedisHolder:
    """Cliente Redis compartilhado. O sistema funciona (degradado) sem Redis."""

    def __init__(self) -> None:
        self.client: aioredis.Redis | None = None
        self.healthy = False

    def init(self, url: str) -> None:
        self.client = aioredis.from_url(
            url, decode_responses=True, socket_connect_timeout=1.0, socket_timeout=1.0,
            health_check_interval=15,
        )

    async def ping(self) -> bool:
        if self.client is None:
            self.healthy = False
            return False
        try:
            await self.client.ping()
            if not self.healthy:
                log.info("redis_available")
            self.healthy = True
        except (RedisError, OSError):
            if self.healthy:
                log.warning("redis_unavailable")
            self.healthy = False
        return self.healthy

    async def close(self) -> None:
        if self.client is not None:
            await self.client.aclose()
            self.client = None


redis_holder = RedisHolder()
