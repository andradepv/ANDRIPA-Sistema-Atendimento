from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api.routes import admin, auth, health, menu, operations, public, tables, ws
from app.core.config import Settings, get_settings
from app.core.errors import install_error_handlers
from app.core.logging import request_id_var, setup_logging
from app.core.redis import redis_holder
from app.db.session import db
from app.realtime.manager import ConnectionManager
from app.realtime.relay import Relay

log = logging.getLogger("andripa.http")
API = "/api/v1"


class BodyLimitMiddleware:
    """Rejeita corpos acima do limite (Content-Length ou corpo em streaming)."""

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app, self.max = app, max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        for k, v in scope.get("headers", []):
            if k == b"content-length" and v.isdigit() and int(v) > self.max:
                resp = JSONResponse({"error": {"code": "payload_too_large", "message": "Requisição grande demais.",
                                               "details": {}}}, status_code=413)
                return await resp(scope, receive, send)
        if scope.get("method") in ("GET", "HEAD", "OPTIONS"):
            return await self.app(scope, receive, send)
        # Sem Content-Length confiável: lê o corpo com limite e o reproduz para a aplicação.
        chunks: list[bytes] = []
        total = 0
        while True:
            msg = await receive()
            if msg["type"] != "http.request":
                return
            body = msg.get("body", b"")
            total += len(body)
            if total > self.max:
                resp = JSONResponse({"error": {"code": "payload_too_large", "message": "Requisição grande demais.",
                                               "details": {}}}, status_code=413)
                return await resp(scope, receive, send)
            chunks.append(body)
            if not msg.get("more_body"):
                break
        replayed = False

        async def replay() -> Message:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": b"".join(chunks), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)


class RequestContextMiddleware:
    """Request id, cabeçalhos de segurança, log de acesso e 'wake' do relay após escritas."""

    def __init__(self, app: ASGIApp, relay_getter) -> None:  # noqa: ANN001
        self.app, self.relay_getter = app, relay_getter

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        rid = uuid.uuid4().hex[:16]
        token = request_id_var.set(rid)
        start = time.perf_counter()
        status = 500

        async def _send(msg: Message) -> None:
            nonlocal status
            if msg["type"] == "http.response.start":
                status = msg["status"]
                headers = list(msg.get("headers", []))
                headers += [(b"x-request-id", rid.encode()), (b"x-content-type-options", b"nosniff"),
                            (b"referrer-policy", b"strict-origin-when-cross-origin"),
                            (b"x-frame-options", b"DENY")]
                if scope["path"].startswith("/api"):
                    headers.append((b"cache-control", b"no-store"))
                msg["headers"] = headers
            await send(msg)

        try:
            await self.app(scope, receive, _send)
        finally:
            if scope["method"] not in ("GET", "HEAD", "OPTIONS"):
                relay = self.relay_getter()
                if relay is not None:
                    relay.wake()
            if scope["path"].startswith("/api") and not scope["path"].startswith("/api/v1/health"):
                log.info("request", extra={"method": scope["method"], "path": scope["path"], "status": status,
                                           "duration_ms": round((time.perf_counter() - start) * 1000, 1)})
            request_id_var.reset(token)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    setup_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):  # noqa: ANN202
        db.init(settings.database_url, pool_size=settings.db_pool_size, null_pool=settings.db_null_pool)
        redis_holder.init(settings.redis_url)
        await redis_holder.ping()
        relay = Relay(app.state.manager, settings.outbox_poll_seconds)
        if settings.relay_enabled:
            app.state.relay = relay
            await relay.start()
        log.info("startup", extra={"environment": settings.environment, "redis": redis_holder.healthy})
        try:
            yield
        finally:
            await relay.stop()
            await app.state.manager.close_all()
            await redis_holder.close()
            await db.dispose()

    app = FastAPI(
        title="Andripa — API de atendimento",
        version="1.0.0",
        lifespan=lifespan,
        openapi_url=f"{API}/openapi.json",
        docs_url=f"{API}/docs" if settings.environment != "production" else None,
        redoc_url=None,
    )
    app.state.manager = ConnectionManager()
    app.state.relay = None
    install_error_handlers(app)

    for r in (auth.router, tables.router, operations.router, menu.router, public.router, admin.router,
              health.router, ws.router):
        app.include_router(r, prefix=API)

    app.add_middleware(BodyLimitMiddleware, max_bytes=settings.max_body_bytes)
    app.add_middleware(CORSMiddleware, allow_origins=settings.allowed_origins, allow_credentials=True,
                       allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
                       allow_headers=["content-type", "x-csrf-token", "idempotency-key", "authorization"])
    app.add_middleware(RequestContextMiddleware, relay_getter=lambda: app.state.relay)

    if settings.frontend_dist_dir:
        dist = Path(settings.frontend_dist_dir).resolve()
        index = dist / "index.html"

        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str) -> FileResponse:
            if path.startswith("api/"):
                return JSONResponse({"error": {"code": "not_found", "message": "Não encontrado.", "details": {}}},
                                    status_code=404)  # type: ignore[return-value]
            candidate = (dist / path).resolve()
            if path and candidate.is_file() and dist in candidate.parents:
                headers = {"Cache-Control": "no-cache"} if path in ("sw.js", "manifest.webmanifest") else \
                    {"Cache-Control": "public, max-age=31536000, immutable"} if path.startswith("assets/") else {}
                return FileResponse(candidate, headers=headers)
            return FileResponse(index, headers={"Cache-Control": "no-cache"})

    return app


app = create_app()
