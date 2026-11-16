from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.domain.states import RequestStatus, RequestType, TagStatus
from app.models import DiningTable, Order, ServiceRequest, TableSession, TableTag, User
from app.schemas import (
    OrderItemOut,
    OrderOut,
    ServiceRequestOut,
    SessionBrief,
    TableOut,
    TagBrief,
    TagOut,
    UserOut,
)


def user_out(u: User) -> UserOut:
    return UserOut(id=u.id, name=u.name, username=u.username, role=u.role, active=u.active)


def public_url(t: DiningTable) -> str:
    return f"{get_settings().public_base_url.rstrip('/')}/m/{t.public_code}"


def order_out(o: Order) -> OrderOut:
    return OrderOut(
        id=o.id,
        number=o.number,
        note=o.note,
        total_cents=o.total_cents,
        items=[OrderItemOut.model_validate(i) for i in o.items],
    )


def request_out(r: ServiceRequest) -> ServiceRequestOut:
    return ServiceRequestOut(
        id=r.id,
        session_id=r.session_id,
        table_id=r.table_id,
        table_number=r.table.number,
        table_name=r.table.name,
        type=r.type,
        status=r.status,
        note=r.note,
        order=order_out(r.order) if r.order else None,
        created_at=r.created_at,
        completed_at=r.completed_at,
        completed_by_name=r.completed_by.name if r.completed_by else None,
        version=r.version,
    )


async def tables_out(db: AsyncSession, tables: list[DiningTable], *, include_join_code: bool = True) -> list[TableOut]:
    session_ids = [t.current_session_id for t in tables if t.current_session_id]
    sessions: dict[uuid.UUID, TableSession] = {}
    pending: dict[tuple[uuid.UUID, RequestType], int] = {}
    if session_ids:
        rows = (await db.execute(select(TableSession).where(TableSession.id.in_(session_ids)))).unique().scalars()
        sessions = {s.id: s for s in rows}
        for sid, rtype, n in (
            await db.execute(
                select(ServiceRequest.session_id, ServiceRequest.type, func.count())
                .where(
                    ServiceRequest.session_id.in_(session_ids),
                    ServiceRequest.status == RequestStatus.PENDENTE,
                )
                .group_by(ServiceRequest.session_id, ServiceRequest.type)
            )
        ).all():
            pending[(sid, rtype)] = n

    tags: dict[uuid.UUID, TableTag] = {}
    if tables:
        # Situação mais recente da etiqueta de cada mesa (tentativas substituídas não contam).
        trows = (
            (
                await db.execute(
                    select(TableTag)
                    .where(TableTag.table_id.in_([t.id for t in tables]), TableTag.status != TagStatus.SUBSTITUIDA)
                    .distinct(TableTag.table_id)
                    .order_by(TableTag.table_id, TableTag.created_at.desc())
                )
            )
            .unique()
            .scalars()
        )
        tags = {g.table_id: g for g in trows}

    out = []
    for t in tables:
        g = tags.get(t.id)
        s = sessions.get(t.current_session_id) if t.current_session_id else None
        out.append(
            TableOut(
                id=t.id,
                number=t.number,
                name=t.name,
                status=t.status,
                active=t.active,
                public_url=public_url(t),
                version=t.version,
                session=SessionBrief(
                    id=s.id,
                    opened_at=s.opened_at,
                    opened_by_name=s.opened_by.name,
                )
                if s
                else None,
                pending_calls=pending.get((s.id, RequestType.CHAMAR_ATENDENTE), 0) if s else 0,
                pending_orders=pending.get((s.id, RequestType.NOVO_PEDIDO), 0) if s else 0,
                bill_requested=bool(pending.get((s.id, RequestType.PEDIR_CONTA), 0)) if s else False,
                tag=TagBrief(id=g.id, status=g.status, uid=g.uid, error=g.error, updated_at=g.updated_at) if g else None,
            )
        )
    return out


async def table_out(db: AsyncSession, t: DiningTable) -> TableOut:
    return (await tables_out(db, [t]))[0]


def tag_out(g: TableTag) -> TagOut:
    return TagOut(
        id=g.id,
        table_id=g.table_id,
        table_number=g.table.number,
        table_name=g.table.name,
        status=g.status,
        url=g.url,
        uid=g.uid,
        error=g.error,
        started_by_name=g.started_by.name,
        lock_authorized_at=g.lock_authorized_at,
        written_at=g.written_at,
        locked_at=g.locked_at,
        created_at=g.created_at,
        updated_at=g.updated_at,
        version=g.version,
    )