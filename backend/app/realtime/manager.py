"""Conexões WebSocket locais desta instância e roteamento de eventos."""
from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

from fastapi import WebSocket

log = logging.getLogger("andripa.ws")

CLOSE_SESSION_ENDED = 4001
CLOSE_UNAUTHORIZED = 4003


@dataclass(eq=False)
class Conn:
    ws: WebSocket
    kind: str  # "staff" | "customer"
    establishment_id: uuid.UUID
    session_id: uuid.UUID | None = None          # sessão da mesa (cliente)
    staff_session_id: uuid.UUID | None = None    # sessão de login (funcionário)
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    queue: asyncio.Queue[dict[str, Any] | None] = field(default_factory=lambda: asyncio.Queue(maxsize=500))


class ConnectionManager:
    def __init__(self) -> None:
        self.conns: dict[uuid.UUID, Conn] = {}
        self._seen: OrderedDict[int, None] = OrderedDict()  # ids já entregues localmente

    def add(self, c: Conn) -> None:
        self.conns[c.id] = c

    def remove(self, c: Conn) -> None:
        self.conns.pop(c.id, None)

    def mark_seen(self, event_id: int) -> bool:
        """True se o evento ainda não foi entregue por esta instância."""
        if event_id in self._seen:
            return False
        self._seen[event_id] = None
        if len(self._seen) > 20_000:
            self._seen.popitem(last=False)
        return True

    def _targets(self, ev: dict[str, Any]) -> list[Conn]:
        audience = set(ev.get("audience", []))
        est = ev["establishment_id"]
        sid = ev.get("session_id")
        out = []
        for c in self.conns.values():
            if str(c.establishment_id) != est:
                continue
            if c.kind == "staff" and "staff" in audience:
                out.append(c)
            elif c.kind == "customer" and (
                "customers" in audience or ("session" in audience and sid and str(c.session_id) == sid)
            ):
                out.append(c)
        return out

    async def deliver(self, ev: dict[str, Any]) -> None:
        if not self.mark_seen(int(ev["id"])):
            return
        msg = {"id": ev["id"], "type": ev["type"], "data": ev["data"], "created_at": ev.get("created_at")}
        for c in self._targets(ev):
            try:
                c.queue.put_nowait(msg)
            except asyncio.QueueFull:
                log.warning("ws_slow_consumer_closed", extra={"conn": str(c.id)})
                await self.close(c, 1013)  # o cliente reconecta e ressincroniza por REST
        # Efeitos de controle: encerrar conexões revogadas.
        if ev["type"] == "session.closed":
            sid = ev["data"].get("session_id")
            for c in list(self.conns.values()):
                if c.kind == "customer" and str(c.session_id) == sid:
                    await self.close(c, CLOSE_SESSION_ENDED, flush=True)
        elif ev["type"] == "staff.session_revoked":
            ids = set(ev["data"].get("staff_session_ids", []))
            for c in list(self.conns.values()):
                if c.kind == "staff" and str(c.staff_session_id) in ids:
                    await self.close(c, CLOSE_UNAUTHORIZED)

    async def close(self, c: Conn, code: int, *, flush: bool = False) -> None:
        if flush:
            # dá tempo para o writer enviar mensagens já enfileiradas
            for _ in range(20):
                if c.queue.empty():
                    break
                await asyncio.sleep(0.01)
        self.remove(c)
        with contextlib.suppress(Exception):
            await c.ws.close(code=code)

    async def close_all(self) -> None:
        for c in list(self.conns.values()):
            await self.close(c, 1012)
