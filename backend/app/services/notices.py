"""Avisos aos clientes: só informam. Para saber mais ou aproveitar, o cliente chama um atendente."""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import StaffCtx
from app.core.config import get_settings
from app.core.errors import not_found
from app.core.ratelimit import hit
from app.models import Notice
from app.schemas import NoticeCreatedOut, NoticeIn, NoticeOut, NoticePatch
from app.services import push as push_svc
from app.services.audit import audit
from app.services.events import CUSTOMERS, STAFF, emit


def _changed(db: AsyncSession, est_id: uuid.UUID) -> None:
    emit(db, est_id, "notices.updated", {}, audience=(STAFF, CUSTOMERS))


async def list_all(db: AsyncSession, est_id: uuid.UUID) -> list[NoticeOut]:
    rows = (await db.execute(select(Notice).where(Notice.establishment_id == est_id)
                             .order_by(Notice.created_at.desc()))).scalars().all()
    return [NoticeOut.model_validate(n) for n in rows]


async def list_active(db: AsyncSession, est_id: uuid.UUID) -> list[NoticeOut]:
    rows = (await db.execute(select(Notice).where(Notice.establishment_id == est_id, Notice.active.is_(True))
                             .order_by(Notice.created_at.desc()).limit(20))).scalars().all()
    return [NoticeOut.model_validate(n) for n in rows]


async def create(db: AsyncSession, ctx: StaffCtx, data: NoticeIn) -> NoticeCreatedOut:
    n = Notice(establishment_id=ctx.establishment_id, title=data.title, message=data.message or None,
               active=data.active)
    db.add(n)
    await db.flush()
    await db.refresh(n)
    audit(db, establishment_id=ctx.establishment_id, actor_id=ctx.user.id, action="notice.create",
          target_type="notice", target_id=n.id, details={"title": n.title, "push": data.send_push})
    _changed(db, ctx.establishment_id)
    out = NoticeOut.model_validate(n)
    await db.commit()
    push = None
    if data.send_push and get_settings().push_enabled:
        await hit(f"broadcast:{ctx.establishment_id}", 5, 3600)
        push = await push_svc.broadcast(db, ctx.establishment_id, n.title,
                                        (n.message or "Chame um atendente para saber mais.")[:240])
    return NoticeCreatedOut(notice=out, push=push)


async def _get(db: AsyncSession, est_id: uuid.UUID, notice_id: uuid.UUID) -> Notice:
    n = (await db.execute(select(Notice).where(Notice.id == notice_id, Notice.establishment_id == est_id))).scalar_one_or_none()
    if n is None:
        raise not_found("Aviso")
    return n


async def patch(db: AsyncSession, ctx: StaffCtx, notice_id: uuid.UUID, data: NoticePatch) -> NoticeOut:
    n = await _get(db, ctx.establishment_id, notice_id)
    changes = data.model_dump(exclude_unset=True)
    for k, v in changes.items():
        setattr(n, k, v)
    await db.flush()
    await db.refresh(n)
    audit(db, establishment_id=ctx.establishment_id, actor_id=ctx.user.id, action="notice.update",
          target_type="notice", target_id=n.id, details=changes)
    _changed(db, ctx.establishment_id)
    return NoticeOut.model_validate(n)


async def delete(db: AsyncSession, ctx: StaffCtx, notice_id: uuid.UUID) -> None:
    n = await _get(db, ctx.establishment_id, notice_id)
    await db.delete(n)
    audit(db, establishment_id=ctx.establishment_id, actor_id=ctx.user.id, action="notice.delete",
          target_type="notice", target_id=notice_id, details={"title": n.title})
    _changed(db, ctx.establishment_id)
