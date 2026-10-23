"""Relay do outbox (PostgreSQL → Redis Pub/Sub) e assinante (Redis → WebSockets locais).

Garantias:
- Eventos só existem se a transação de negócio fez COMMIT (outbox na mesma transação).
- Publicação é *at-least-once*; clientes deduplicam pelo `id` do evento e pela `version` das entidades.
- Sem Redis, cada instância entrega localmente lendo o outbox (degradação controlada) e o evento
  continua pendente até o Redis voltar.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from redis.exceptions import RedisError
from sqlalchemy import select, update

from app.core.redis import redis_holder
from app.db.session import db
from app.models import OutboxEvent
from app.realtime.manager import ConnectionManager

log = logging.getLogger("andripa.relay")
CHANNEL = "andripa:events"
STALE_AFTER = timedelta(minutes=10)


def envelope(e: OutboxEvent) -> dict[str, Any]:
    return {
        "id": e.id, "type": e.type, "establishment_id": str(e.establishment_id),
        "session_id": str(e.session_id) if e.session_id else None,
        "audience": e.payload.get("audience", []), "data": e.payload.get("data", {}),
        "created_at": e.created_at.isoformat() if e.created_at else None,
    }


class Relay:
    def __init__(self, manager: ConnectionManager, poll_seconds: float = 0.5) -> None:
        self.manager = manager
        self.poll_seconds = poll_seconds
        self._wake = asyncio.Event()
        self._tasks: list[asyncio.Task[None]] = []
        self._stopping = False

    def wake(self) -> None:
        self._wake.set()

    async def start(self) -> None:
        self._tasks = [asyncio.create_task(self._relay_loop(), name="outbox-relay"),
                       asyncio.create_task(self._subscribe_loop(), name="redis-subscriber")]

    async def stop(self) -> None:
        self._stopping = True
        self._wake.set()
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await t

    async def _relay_loop(self) -> None:
        while not self._stopping:
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._wake.wait(), timeout=self.poll_seconds)
            self._wake.clear()
            try:
                while await self.run_once():
                    pass
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — o relay nunca pode morrer
                log.exception("relay_iteration_failed")
                await asyncio.sleep(1)

    async def run_once(self, batch: int = 200) -> bool:
        """Processa um lote. Retorna True se pode haver mais eventos pendentes."""
        redis_ok = redis_holder.healthy or await redis_holder.ping()
        async with db.session() as s:
            rows = (await s.execute(
                select(OutboxEvent).where(OutboxEvent.published_at.is_(None))
                .order_by(OutboxEvent.id).limit(batch).with_for_update(skip_locked=True)
            )).scalars().all()
            if not rows:
                return False
            now = datetime.now(UTC)
            published: list[int] = []
            if redis_ok and redis_holder.client is not None:
                try:
                    pipe = redis_holder.client.pipeline(transaction=False)
                    for e in rows:
                        if e.created_at and now - e.created_at > STALE_AFTER:
                            continue  # clientes ressincronizam por REST; não reenviar eventos velhos
                        pipe.publish(CHANNEL, json.dumps(envelope(e), default=str))
                    await pipe.execute()
                    published = [e.id for e in rows]
                except (RedisError, OSError):
                    redis_holder.healthy = False
                    log.warning("redis_publish_failed_degraded_mode")
            if not published:
                # Degradado: entrega local, mantém pendente. Commit libera os locks para outras instâncias.
                for e in rows:
                    await self.manager.deliver(envelope(e))  # deduplicado por id no manager
                stale = [e.id for e in rows if e.created_at and now - e.created_at > STALE_AFTER]
                if stale:
                    await s.execute(update(OutboxEvent).where(OutboxEvent.id.in_(stale)).values(published_at=now))
                await s.execute(update(OutboxEvent).where(OutboxEvent.id.in_([e.id for e in rows]))
                                .values(attempts=OutboxEvent.attempts + 1))
                await s.commit()
                return False
            await s.execute(update(OutboxEvent).where(OutboxEvent.id.in_(published)).values(published_at=now))
            await s.commit()
            # Entrega local imediata (o subscriber deduplica quando a mensagem do Redis chegar).
            for e in rows:
                await self.manager.deliver(envelope(e))
            return len(rows) == batch

    async def _subscribe_loop(self) -> None:
        backoff = 0.5
        while not self._stopping:
            if redis_holder.client is None:
                await asyncio.sleep(1)
                continue
            pubsub = redis_holder.client.pubsub(ignore_subscribe_messages=True)
            try:
                await pubsub.subscribe(CHANNEL)
                redis_holder.healthy = True
                backoff = 0.5
                self.wake()  # publica o que ficou pendente durante a indisponibilidade
                while not self._stopping:
                    msg = await pubsub.get_message(timeout=5.0)
                    if msg is None:
                        if not await redis_holder.ping():
                            raise RedisError("ping failed")
                        continue
                    if msg.get("type") == "message":
                        try:
                            ev = json.loads(msg["data"])
                            await self.manager.deliver(ev)
                        except (ValueError, KeyError):
                            log.warning("invalid_event_message")
            except asyncio.CancelledError:
                raise
            except (RedisError, OSError):
                redis_holder.healthy = False
                log.warning("redis_subscriber_disconnected", extra={"retry_in": backoff})
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 15)
            finally:
                with contextlib.suppress(Exception):
                    await pubsub.aclose()
