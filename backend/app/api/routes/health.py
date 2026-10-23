from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.redis import redis_holder
from app.db.session import db

router = APIRouter(tags=["health"])


@router.get("/health/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready")
async def ready() -> JSONResponse:
    """Pronto = PostgreSQL acessível. Redis indisponível é reportado como degradado, não falha."""
    db_ok = True
    try:
        async with db.session() as s:
            await s.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        db_ok = False
    redis_ok = await redis_holder.ping()
    body = {"status": "ok" if db_ok and redis_ok else ("degraded" if db_ok else "down"),
            "database": db_ok, "redis": redis_ok}
    return JSONResponse(body, status_code=200 if db_ok else 503)
