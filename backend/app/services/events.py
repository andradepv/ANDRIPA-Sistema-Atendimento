"""Transactional outbox: eventos são gravados na MESMA transação da mudança de estado."""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import OutboxEvent

STAFF = "staff"
SESSION = "session"
CUSTOMERS = "customers"


def emit(
    db: AsyncSession,
    establishment_id: uuid.UUID,
    type_: str,
    data: dict[str, Any],
    *,
    session_id: uuid.UUID | None = None,
    audience: tuple[str, ...] = (STAFF,),
) -> None:
    db.add(
        OutboxEvent(
            establishment_id=establishment_id,
            session_id=session_id,
            type=type_,
            payload={"audience": list(audience), "data": data},
        )
    )
