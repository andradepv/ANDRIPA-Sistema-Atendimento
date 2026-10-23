from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.api.deps import STAFF_COOKIE, load_customer, load_staff_session
from app.core.config import get_settings
from app.db.session import db
from app.realtime.manager import CLOSE_SESSION_ENDED, CLOSE_UNAUTHORIZED, Conn

router = APIRouter()
log = logging.getLogger("andripa.ws")

PING_EVERY = 25
IDLE_TIMEOUT = 75
REVALIDATE_EVERY = 60


def _origin_ok(ws: WebSocket) -> bool:
    origin = ws.headers.get("origin")
    if origin is None:
        return False
    allowed = set(get_settings().allowed_origins)
    host = ws.headers.get("host", "")
    return origin in allowed or origin in (f"https://{host}", f"http://{host}")


async def _run(ws: WebSocket, conn: Conn, revalidate) -> None:  # noqa: ANN001
    manager = ws.app.state.manager
    manager.add(conn)
    loop = asyncio.get_running_loop()
    last_rx = loop.time()

    async def writer() -> None:
        while True:
            msg = await conn.queue.get()
            if msg is None:
                return
            await ws.send_text(json.dumps(msg, default=str))

    async def reader() -> None:
        nonlocal last_rx
        while True:
            raw = await ws.receive_text()
            last_rx = loop.time()
            if len(raw) > 2048:
                await ws.close(code=1009)
                return
            with contextlib.suppress(ValueError):
                if json.loads(raw).get("type") == "ping":
                    await ws.send_text('{"type":"pong"}')

    async def keepalive() -> None:
        ticks = 0
        while True:
            await asyncio.sleep(PING_EVERY)
            ticks += PING_EVERY
            if loop.time() - last_rx > IDLE_TIMEOUT:
                await ws.close(code=1001)
                return
            conn.queue.put_nowait({"type": "ping"})
            if ticks >= REVALIDATE_EVERY:
                ticks = 0
                code = await revalidate()
                if code:
                    await manager.close(conn, code)
                    return

    tasks = [asyncio.create_task(writer()), asyncio.create_task(reader()), asyncio.create_task(keepalive())]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    except WebSocketDisconnect:
        pass
    finally:
        for t in tasks:
            t.cancel()
        for t in tasks:
            with contextlib.suppress(BaseException):
                await t
        manager.remove(conn)


@router.websocket("/ws/staff")
async def staff_ws(ws: WebSocket) -> None:
    if not _origin_ok(ws):
        await ws.close(code=CLOSE_UNAUTHORIZED)
        return
    raw = ws.cookies.get(STAFF_COOKIE)
    async with db.session() as s:
        sess = await load_staff_session(s, raw)
        if sess is None:
            await ws.close(code=CLOSE_UNAUTHORIZED)
            return
        est_id, staff_session_id = sess.user.establishment_id, sess.id
    await ws.accept()
    conn = Conn(ws=ws, kind="staff", establishment_id=est_id, staff_session_id=staff_session_id)
    await ws.send_text(json.dumps({"type": "hello", "kind": "staff"}))

    async def revalidate() -> int | None:
        async with db.session() as s:
            return None if await load_staff_session(s, raw) else CLOSE_UNAUTHORIZED

    await _run(ws, conn, revalidate)


@router.websocket("/ws/customer")
async def customer_ws(ws: WebSocket) -> None:
    if not _origin_ok(ws):
        await ws.close(code=CLOSE_UNAUTHORIZED)
        return
    await ws.accept()
    # O token vai na primeira mensagem (nunca na URL, para não aparecer em logs).
    try:
        first = json.loads(await asyncio.wait_for(ws.receive_text(), timeout=5))
        token = str(first.get("token", "")) if first.get("type") == "auth" else ""
    except (TimeoutError, ValueError, WebSocketDisconnect, AttributeError):
        with contextlib.suppress(Exception):
            await ws.close(code=CLOSE_UNAUTHORIZED)
        return
    async with db.session() as s:
        ctx = await load_customer(s, token)
        if ctx is None:
            await ws.close(code=CLOSE_SESSION_ENDED)
            return
        est_id, session_id = ctx.establishment.id, ctx.session.id
    conn = Conn(ws=ws, kind="customer", establishment_id=est_id, session_id=session_id)
    await ws.send_text(json.dumps({"type": "hello", "kind": "customer", "session_id": str(session_id)}))

    async def revalidate() -> int | None:
        async with db.session() as s:
            return None if await load_customer(s, token) else CLOSE_SESSION_ENDED

    await _run(ws, conn, revalidate)


__all__ = ["router", "uuid"]
