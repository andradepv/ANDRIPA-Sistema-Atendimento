from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime

import httpx
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AppError
from app.models import PushSubscription
from app.schemas import PushBroadcastIn, PushBroadcastOut, PushSubscribeIn
from app.services import webpush

log = logging.getLogger("andripa.push")


def _require_enabled() -> None:
    if not get_settings().push_enabled:
        raise AppError(503, "push_disabled", "Notificações push não estão configuradas neste servidor.")


async def subscribe(db: AsyncSession, est_id: uuid.UUID, data: PushSubscribeIn) -> None:
    _require_enabled()
    sub = data.subscription
    try:  # valida as chaves antes de gravar
        webpush.encrypt(b"x", sub.keys.p256dh, sub.keys.auth)
    except Exception as e:  # noqa: BLE001
        raise AppError(422, "invalid_subscription", "Inscrição push inválida.") from e
    stmt = insert(PushSubscription).values(
        id=uuid.uuid4(), establishment_id=est_id, endpoint=sub.endpoint, p256dh=sub.keys.p256dh,
        auth=sub.keys.auth, consent_marketing=True, revoked_at=None, failure_count=0,
    ).on_conflict_do_update(
        index_elements=[PushSubscription.endpoint],
        set_={"establishment_id": est_id, "p256dh": sub.keys.p256dh, "auth": sub.keys.auth,
              "consent_marketing": True, "revoked_at": None, "failure_count": 0},
    )
    await db.execute(stmt)
    await db.commit()


async def unsubscribe(db: AsyncSession, endpoint: str) -> None:
    await db.execute(update(PushSubscription).where(PushSubscription.endpoint == endpoint)
                     .values(revoked_at=datetime.now(UTC), consent_marketing=False))
    await db.commit()


async def broadcast(db: AsyncSession, est_id: uuid.UUID, data: PushBroadcastIn,
                    client: httpx.AsyncClient | None = None) -> PushBroadcastOut:
    _require_enabled()
    s = get_settings()
    key = webpush.load_vapid_private(s.vapid_private_key)
    subs = (await db.execute(select(PushSubscription).where(
        PushSubscription.establishment_id == est_id, PushSubscription.revoked_at.is_(None),
        PushSubscription.consent_marketing.is_(True)))).scalars().all()
    payload = json.dumps({"title": data.title, "body": data.body, "url": data.url or "/"}).encode()
    own_client = client is None
    client = client or httpx.AsyncClient(timeout=10)
    sem = asyncio.Semaphore(20)
    results: dict[uuid.UUID, int] = {}

    async def _send(sub: PushSubscription) -> None:
        async with sem:
            try:
                body = webpush.encrypt(payload, sub.p256dh, sub.auth)
                r = await client.post(sub.endpoint, content=body, headers={
                    "Authorization": webpush.vapid_header(sub.endpoint, key, s.vapid_public_key, s.vapid_subject),
                    "Content-Encoding": "aes128gcm", "Content-Type": "application/octet-stream",
                    "TTL": "86400", "Urgency": "normal",
                })
                results[sub.id] = r.status_code
            except (httpx.HTTPError, ValueError) as e:
                log.warning("push_send_error", extra={"error": type(e).__name__})
                results[sub.id] = 0

    try:
        await asyncio.gather(*(_send(x) for x in subs))
    finally:
        if own_client:
            await client.aclose()
    sent = failed = removed = 0
    now = datetime.now(UTC)
    for sub in subs:
        code = results.get(sub.id, 0)
        if 200 <= code < 300:
            sent += 1
            sub.last_success_at = now
            sub.failure_count = 0
        elif code in (404, 410):
            removed += 1
            sub.revoked_at = now
        else:
            failed += 1
            sub.failure_count += 1
            if sub.failure_count >= 5:
                sub.revoked_at = now
    await db.commit()
    return PushBroadcastOut(targeted=len(subs), sent=sent, failed=failed, removed=removed)
