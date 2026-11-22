from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CustomerCtx
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.security import new_token, token_hash
from app.domain.states import RequestStatus, RequestType, SessionStatus, TableStatus
from app.models import CustomerToken, DiningTable, Establishment, ServiceRequest, TableSession
from app.schemas import CustomerSessionOut, JoinOut, PublicTableOut
from app.services import tables as table_svc
from app.services.audit import audit
from app.services.events import STAFF, emit
from app.services.serializers import request_out

MAX_TOKENS_PER_SESSION = 60


async def find_table(db: AsyncSession, code: str, *, lock: bool = False) -> tuple[DiningTable, Establishment]:
    if not (10 <= len(code) <= 32) or not code.replace("-", "").replace("_", "").isalnum():
        raise AppError(404, "table_not_found", "Mesa não encontrada.")
    q = select(DiningTable).where(DiningTable.public_code == code)
    if lock:
        q = q.with_for_update().execution_options(populate_existing=True)
    t = (await db.execute(q)).scalar_one_or_none()
    if t is None or not t.active:
        raise AppError(404, "table_not_found", "Mesa não encontrada.")
    est = await db.get(Establishment, t.establishment_id)
    assert est is not None
    return t, est


async def public_table(db: AsyncSession, code: str) -> PublicTableOut:
    t, est = await find_table(db, code)
    return PublicTableOut(
        establishment_name=est.name,
        timezone=est.timezone,
        table_number=t.number,
        table_name=t.name,
        status=t.status,
        available=t.current_session_id is not None,
        awaiting_release=t.status == TableStatus.AGUARDANDO_LIBERACAO,
        orders_enabled=est.orders_enabled,
    )

async def request_open(db: AsyncSession, code: str, ip: str) -> PublicTableOut:
    """Cliente clicou em 'Cliente' com a mesa fechada: muda estado e chama um atendente para liberar."""
    t, est = await find_table(db, code, lock=True)
    if t.current_session_id is not None or t.status == TableStatus.OCUPADA:
        return await public_table(db, code)

    existing = (
        (
            await db.execute(
                select(ServiceRequest).where(
                    ServiceRequest.table_id == t.id,
                    ServiceRequest.type == RequestType.LIBERAR_MESA,
                    ServiceRequest.status == RequestStatus.PENDENTE,
                )
            )
        )
        .unique()
        .scalar_one_or_none()
    )

    if t.status != TableStatus.AGUARDANDO_LIBERACAO:
        t.status = TableStatus.AGUARDANDO_LIBERACAO
        t.version += 1

    if existing is None:
        req = ServiceRequest(
            establishment_id=t.establishment_id,
            session_id=None,
            table_id=t.id,
            type=RequestType.LIBERAR_MESA,
            status=RequestStatus.PENDENTE,
        )
        db.add(req)
        await db.flush()
        req = (
            (
                await db.execute(
                    select(ServiceRequest).where(ServiceRequest.id == req.id).execution_options(populate_existing=True)
                )
            )
            .unique()
            .scalar_one()
        )
        emit(
            db,
            t.establishment_id,
            "request.updated",
            {"request": request_out(req).model_dump(mode="json")},
            audience=(STAFF,),
        )
        audit(
            db,
            establishment_id=t.establishment_id,
            actor_kind="CLIENTE",
            action="table.request_open",
            target_type="table",
            target_id=t.id,
            details={"table": t.number},
            ip=ip,
        )

    await table_svc.emit_table(db, t)
    await db.commit()
    return await public_table(db, code)


async def join(db: AsyncSession, code: str) -> JoinOut:
    t, _ = await find_table(db, code)
    if t.current_session_id is None:
        raise AppError(409, "table_not_open", "Esta mesa ainda não foi liberada.")
    s = (
        (
            await db.execute(
                select(TableSession)
                .where(TableSession.id == t.current_session_id)
                .with_for_update(of=TableSession)
                .execution_options(populate_existing=True)
            )
        )
        .unique()
        .scalar_one()
    )
    if s.status != SessionStatus.OPEN:
        raise AppError(409, "table_not_open", "Esta mesa ainda não foi liberada.")
    count = (await db.execute(select(func.count()).where(CustomerToken.session_id == s.id))).scalar_one()
    if count >= MAX_TOKENS_PER_SESSION:
        raise AppError(429, "too_many_devices", "Limite de aparelhos para esta mesa atingido. Chame o atendente.")
    raw = new_token()
    expires = min(
        datetime.now(UTC) + timedelta(hours=get_settings().customer_token_ttl_hours), s.opened_at + timedelta(hours=24)
    )
    db.add(CustomerToken(session_id=s.id, token_hash=token_hash(raw), expires_at=expires))
    await db.commit()
    return JoinOut(token=raw, expires_at=expires)


async def session_state(db: AsyncSession, ctx: CustomerCtx) -> CustomerSessionOut:
    reqs = (
        (
            await db.execute(
                select(ServiceRequest)
                .where(ServiceRequest.session_id == ctx.session.id)
                .order_by(ServiceRequest.created_at.desc())
                .limit(100)
            )
        )
        .unique()
        .scalars()
        .all()
    )
    settings = get_settings()
    return CustomerSessionOut(
        session_id=ctx.session.id,
        establishment_name=ctx.establishment.name,
        timezone=ctx.establishment.timezone,
        table_number=ctx.table.number,
        table_name=ctx.table.name,
        orders_enabled=ctx.establishment.orders_enabled,
        opened_at=ctx.session.opened_at,
        requests=[request_out(r) for r in reqs],
        push_public_key=settings.vapid_public_key if settings.push_enabled else None,
    )
