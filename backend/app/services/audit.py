from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog


def audit(
    db: AsyncSession,
    *,
    establishment_id: uuid.UUID,
    action: str,
    actor_id: uuid.UUID | None = None,
    actor_kind: str = "STAFF",
    target_type: str | None = None,
    target_id: Any = None,
    details: dict[str, Any] | None = None,
    ip: str | None = None,
) -> None:
    db.add(
        AuditLog(
            establishment_id=establishment_id,
            actor_id=actor_id,
            actor_kind=actor_kind,
            action=action,
            target_type=target_type,
            target_id=str(target_id) if target_id is not None else None,
            details=details or {},
            ip=ip,
        )
    )
