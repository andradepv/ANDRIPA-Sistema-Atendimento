"""Rate limiting por janela fixa. Usa Redis (compartilhado entre instâncias) e cai para
um limitador em memória por instância quando o Redis está indisponível."""
from __future__ import annotations

import time

from fastapi import Request
from redis.exceptions import RedisError

from app.core.errors import AppError
from app.core.redis import redis_holder

_local: dict[str, tuple[int, float]] = {}


def _local_hit(key: str, window: int) -> int:
    now = time.monotonic()
    count, start = _local.get(key, (0, now))
    if now - start >= window:
        count, start = 0, now
    count += 1
    _local[key] = (count, start)
    if len(_local) > 50_000:  # evita crescimento ilimitado
        for k in list(_local)[:10_000]:
            _local.pop(k, None)
    return count


async def hit(key: str, limit: int, window_seconds: int) -> None:
    full = f"rl:{key}:{int(time.time() // window_seconds)}"
    count: int
    client = redis_holder.client
    try:
        if client is None:
            raise RedisError("no client")
        pipe = client.pipeline()
        pipe.incr(full)
        pipe.expire(full, window_seconds + 1)
        count = int((await pipe.execute())[0])
    except (RedisError, OSError):
        count = _local_hit(full, window_seconds)
    if count > limit:
        raise AppError(429, "rate_limited", "Muitas tentativas. Aguarde alguns instantes.")


def client_ip(request: Request) -> str:
    # Atrás do ALB/CloudFront o uvicorn roda com --proxy-headers e --forwarded-allow-ips,
    # então request.client já reflete o IP real.
    return request.client.host if request.client else "unknown"


def reset_local() -> None:
    _local.clear()
