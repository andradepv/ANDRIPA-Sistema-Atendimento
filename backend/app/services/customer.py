from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CustomerCtx
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.ratelimit import hit
from app.core.security import constant_time_eq, new_token, token_hash
from app.domain.states import SessionStatus
from app.models import CustomerToken, DiningTable, Establishment, Order, ServiceRequest, TableSession
from app.schemas import CustomerSessionOut, JoinIn, JoinOut, PublicTableOut
from app.services.serializers import order_out, request_out
from app.services.tables import session_totals

MAX_TOKENS_PER_SESSION = 60


async def find_table(db: AsyncSession, code: str) -> tuple[DiningTable, Establishment]:
    if not (10 <= len(code) <= 32) or not code.replace("-", "").replace("_", "").isalnum():
        raise AppError(404, "table_not_found", "Mesa não encontrada.")
    t = (await db.execute(select(DiningTable).where(DiningTable.public_code == code))).scalar_one_or_none()
    if t is None or not t.active:
        raise AppError(404, "table_not_found", "Mesa não encontrada.")
    est = await db.get(Establishment, t.establishment_id)
    assert est is not None
    return t, est


async def public_table(db: AsyncSession, code: str) -> PublicTableOut:
    t, est = await find_table(db, code)
    return PublicTableOut(
        establishment_name=est.name, timezone=est.timezone, table_number=t.number, table_name=t.name,
        available=t.current_session_id is not None, join_code_required=est.join_code_required,
        orders_enabled=est.orders_enabled,
    )


async def join(db: AsyncSession, code: str, data: JoinIn, ip: str) -> JoinOut:
    t, est = await find_table(db, code)
    if t.current_session_id is None:
        raise AppError(409, "table_not_open", "Esta mesa não está disponível para atendimento digital.")
    s = (await db.execute(select(TableSession).where(TableSession.id == t.current_session_id)
                          .with_for_update(of=TableSession).execution_options(populate_existing=True))).unique().scalar_one()
    if s.status != SessionStatus.OPEN:
        raise AppError(409, "table_not_open", "Esta mesa não está disponível para atendimento digital.")
    if est.join_code_required:
        await hit(f"joinfail:ip:{ip}", 10, 600)  # conta tentativas (sucesso também consome)
        await hit(f"joinfail:session:{s.id}", 30, 600)
        if not data.join_code or not constant_time_eq(data.join_code, s.join_code):
            raise AppError(403, "invalid_join_code", "Código da mesa incorreto. Peça o código ao atendente.")
    count = (await db.execute(select(func.count()).where(CustomerToken.session_id == s.id))).scalar_one()
    if count >= MAX_TOKENS_PER_SESSION:
        raise AppError(429, "too_many_devices", "Limite de aparelhos para esta mesa atingido. Chame o atendente.")
    raw = new_token()
    expires = min(datetime.now(UTC) + timedelta(hours=get_settings().customer_token_ttl_hours),
                  s.opened_at + timedelta(hours=24))
    db.add(CustomerToken(session_id=s.id, token_hash=token_hash(raw), expires_at=expires))
    await db.commit()
    return JoinOut(token=raw, expires_at=expires)


async def session_state(db: AsyncSession, ctx: CustomerCtx) -> CustomerSessionOut:
    reqs = (await db.execute(select(ServiceRequest).where(ServiceRequest.session_id == ctx.session.id)
                             .order_by(ServiceRequest.created_at.desc()).limit(50))).unique().scalars().all()
    orders = (await db.execute(select(Order).where(Order.session_id == ctx.session.id)
                               .order_by(Order.created_at.desc()))).unique().scalars().all()
    subtotal, _ = await session_totals(db, ctx.session.id)
    settings = get_settings()
    return CustomerSessionOut(
        session_id=ctx.session.id, establishment_name=ctx.establishment.name, timezone=ctx.establishment.timezone,
        table_number=ctx.table.number, table_name=ctx.table.name, table_status=ctx.table.status,
        orders_enabled=ctx.establishment.orders_enabled, opened_at=ctx.session.opened_at,
        requests=[request_out(r) for r in reqs], orders=[order_out(o) for o in orders], total_cents=subtotal,
        push_public_key=settings.vapid_public_key if settings.push_enabled else None,
    )
