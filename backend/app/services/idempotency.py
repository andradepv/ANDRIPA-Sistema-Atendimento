"""Idempotência por cabeçalho `Idempotency-Key`.

Requisições com a mesma chave são serializadas por um advisory lock transacional;
a resposta original é armazenada na mesma transação da operação e devolvida nas repetições.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models import IdempotencyKey

KEY_PATTERN = r"^[A-Za-z0-9_\-:.]{8,80}$"


def body_hash(body: Any) -> str:
    if isinstance(body, BaseModel):
        body = body.model_dump(mode="json")
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()


async def run_idempotent(
    db: AsyncSession,
    *,
    scope: str,
    key: str | None,
    request_body: Any,
    status_code: int,
    action: Callable[[], Awaitable[BaseModel]],
) -> JSONResponse:
    """Executa `action` (que NÃO deve fazer commit) e confirma a transação junto com a chave."""
    if key is None:
        result = await action()
        await db.commit()
        return JSONResponse(result.model_dump(mode="json"), status_code=status_code)

    import re

    if not re.match(KEY_PATTERN, key):
        raise AppError(422, "invalid_idempotency_key", "Idempotency-Key inválida.")

    rhash = body_hash(request_body)
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
                     {"k": f"{scope}|{key}"})
    existing = (await db.execute(
        select(IdempotencyKey).where(IdempotencyKey.scope == scope, IdempotencyKey.key == key)
    )).scalar_one_or_none()
    if existing is not None:
        stored_hash, stored_resp, stored_code = existing.request_hash, existing.response, existing.status_code
        await db.rollback()
        if stored_hash != rhash:
            raise AppError(422, "idempotency_key_reused",
                           "Esta Idempotency-Key já foi usada com outro conteúdo.")
        return JSONResponse(stored_resp, status_code=stored_code, headers={"Idempotent-Replay": "true"})

    result = await action()
    payload = result.model_dump(mode="json")
    db.add(IdempotencyKey(scope=scope, key=key, request_hash=rhash, status_code=status_code,
                          response=payload))
    await db.commit()
    return JSONResponse(payload, status_code=status_code)
