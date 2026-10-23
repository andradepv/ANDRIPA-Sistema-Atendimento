from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.domain.states import ACTIVE_REQUEST_STATUSES, PENDING_ORDER_STATUSES
from app.models import DiningTable, Order, ServiceRequest, TableSession, User
from app.schemas import (
    OrderItemOut,
    OrderOut,
    ServiceRequestOut,
    SessionBrief,
    TableOut,
    UserOut,
)


def user_out(u: User) -> UserOut:
    return UserOut(id=u.id, name=u.name, email=u.email, role=u.role, active=u.active,
                   has_pin=bool(u.pin_hash))


def public_url(t: DiningTable) -> str:
    return f"{get_settings().public_base_url.rstrip('/')}/m/{t.public_code}"


def request_out(r: ServiceRequest) -> ServiceRequestOut:
    return ServiceRequestOut(
        id=r.id, session_id=r.session_id, table_id=r.table_id, table_number=r.table.number,
        table_name=r.table.name, type=r.type, status=r.status, priority=r.priority, note=r.note,
        order_id=r.order_id, origin=r.origin, assigned_to_id=r.assigned_to_id,
        assigned_to_name=r.assigned_to.name if r.assigned_to else None,
        created_at=r.created_at, updated_at=r.updated_at, claimed_at=r.claimed_at,
        completed_at=r.completed_at, version=r.version,
    )


def order_out(o: Order) -> OrderOut:
    return OrderOut(
        id=o.id, number=o.number, session_id=o.session_id, table_id=o.table_id,
        table_number=o.table.number, status=o.status, origin=o.origin, note=o.note,
        total_cents=o.total_cents, created_at=o.created_at, updated_at=o.updated_at,
        version=o.version, items=[OrderItemOut.model_validate(i) for i in o.items],
    )


async def tables_out(db: AsyncSession, tables: list[DiningTable], *, include_join_code: bool = True) -> list[TableOut]:
    session_ids = [t.current_session_id for t in tables if t.current_session_id]
    sessions: dict[uuid.UUID, TableSession] = {}
    req_counts: dict[uuid.UUID, int] = {}
    ord_counts: dict[uuid.UUID, int] = {}
    if session_ids:
        rows = (await db.execute(select(TableSession).where(TableSession.id.in_(session_ids)))).scalars()
        sessions = {s.id: s for s in rows}
        for sid, n in (await db.execute(
            select(ServiceRequest.session_id, func.count()).where(
                ServiceRequest.session_id.in_(session_ids),
                ServiceRequest.status.in_(ACTIVE_REQUEST_STATUSES),
            ).group_by(ServiceRequest.session_id)
        )).all():
            req_counts[sid] = n
        for sid, n in (await db.execute(
            select(Order.session_id, func.count()).where(
                Order.session_id.in_(session_ids), Order.status.in_(PENDING_ORDER_STATUSES),
            ).group_by(Order.session_id)
        )).all():
            ord_counts[sid] = n
    out = []
    for t in tables:
        s = sessions.get(t.current_session_id) if t.current_session_id else None
        out.append(TableOut(
            id=t.id, number=t.number, name=t.name, status=t.status, active=t.active,
            public_url=public_url(t), version=t.version,
            session=SessionBrief(
                id=s.id, label=s.label, opened_at=s.opened_at, opened_by_name=s.opened_by.name,
                join_code=s.join_code if include_join_code else None,
                close_requested_at=s.close_requested_at,
            ) if s else None,
            pending_requests=req_counts.get(s.id, 0) if s else 0,
            pending_orders=ord_counts.get(s.id, 0) if s else 0,
        ))
    return out


async def table_out(db: AsyncSession, t: DiningTable) -> TableOut:
    return (await tables_out(db, [t]))[0]
