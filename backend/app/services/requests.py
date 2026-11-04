"""Solicitações da mesa: chamar atendente, pedido do cardápio e pedir a conta.

Cada uma só tem dois momentos: foi feita (PENDENTE) e foi resolvida (CONCLUIDA), com o horário de cada um.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CustomerCtx, StaffCtx
from app.core.errors import AppError, conflict, not_found
from app.core.permissions import Perm
from app.domain.states import RequestStatus, RequestType
from app.models import DiningTable, ServiceRequest
from app.schemas import ServiceRequestOut
from app.services import tables as table_svc
from app.services.audit import audit
from app.services.events import SESSION, STAFF, emit
from app.services.serializers import request_out


def now() -> datetime:
    return datetime.now(UTC)


async def load(db: AsyncSession, request_id: uuid.UUID) -> ServiceRequest:
    return (await db.execute(select(ServiceRequest).where(ServiceRequest.id == request_id)
                             .execution_options(populate_existing=True))).unique().scalar_one()


def emit_request(db: AsyncSession, r: ServiceRequest) -> ServiceRequestOut:
    out = request_out(r)
    emit(db, r.establishment_id, "request.updated", {"request": out.model_dump(mode="json")},
         session_id=r.session_id, audience=(STAFF, SESSION))
    return out


async def customer_create(db: AsyncSession, ctx: CustomerCtx, type_: str, note: str | None) -> ServiceRequestOut:
    rtype = RequestType(type_)
    # Bloqueia a mesa para serializar solicitações da mesma sessão (e com o encerramento).
    table = (await db.execute(select(DiningTable).where(DiningTable.id == ctx.table.id)
                              .with_for_update().execution_options(populate_existing=True))).scalar_one()
    if table.current_session_id != ctx.session.id:
        raise AppError(401, "session_ended", "Esta sessão da mesa foi encerrada.")
    existing = (await db.execute(select(ServiceRequest).where(
        ServiceRequest.session_id == ctx.session.id, ServiceRequest.type == rtype,
        ServiceRequest.status == RequestStatus.PENDENTE))).unique().scalar_one_or_none()
    if existing is not None:
        # Não duplica: devolve a solicitação que já está aguardando.
        return request_out(existing)
    r = ServiceRequest(establishment_id=table.establishment_id, session_id=ctx.session.id, table_id=table.id,
                       type=rtype, status=RequestStatus.PENDENTE, note=note)
    db.add(r)
    try:
        await db.flush()
    except IntegrityError as e:
        raise conflict("request_already_active", "Já existe uma solicitação aguardando.") from e
    r = await load(db, r.id)
    audit(db, establishment_id=table.establishment_id, actor_kind="CLIENTE", action="request.create",
          target_type="service_request", target_id=r.id, details={"type": rtype.value, "table": table.number})
    out = emit_request(db, r)
    await table_svc.emit_table(db, table)
    return out


async def customer_cancel(db: AsyncSession, ctx: CustomerCtx, request_id: uuid.UUID) -> ServiceRequestOut:
    r = (await db.execute(select(ServiceRequest).where(
        ServiceRequest.id == request_id, ServiceRequest.session_id == ctx.session.id)
        .with_for_update(of=ServiceRequest).execution_options(populate_existing=True))).unique().scalar_one_or_none()
    if r is None:
        raise not_found("Chamado")
    if r.status != RequestStatus.PENDENTE or r.type != RequestType.CHAMAR_ATENDENTE:
        raise conflict("cannot_cancel", "Este chamado não pode mais ser cancelado.")
    r.status = RequestStatus.CANCELADA
    r.completed_at = now()
    r.version += 1
    await db.flush()
    r = await load(db, r.id)
    table = await db.get(DiningTable, r.table_id)
    assert table is not None
    out = emit_request(db, r)
    await table_svc.emit_table(db, table)
    return out


async def list_pending(db: AsyncSession, est_id: uuid.UUID, *, limit: int, offset: int,
                       session_id: uuid.UUID | None = None) -> tuple[list[ServiceRequestOut], int]:
    q = select(ServiceRequest).where(ServiceRequest.establishment_id == est_id,
                                     ServiceRequest.status == RequestStatus.PENDENTE)
    if session_id:
        q = q.where(ServiceRequest.session_id == session_id)
    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
    rows = (await db.execute(q.order_by(ServiceRequest.created_at).limit(limit).offset(offset))).unique().scalars().all()
    return [request_out(r) for r in rows], int(total)


async def complete(db: AsyncSession, ctx: StaffCtx, request_id: uuid.UUID, ip: str | None) -> ServiceRequestOut:
    """Atendido / repassado à cozinha / conta finalizada (esta última encerra a mesa)."""
    r = (await db.execute(select(ServiceRequest).where(
        ServiceRequest.id == request_id, ServiceRequest.establishment_id == ctx.establishment_id))).unique().scalar_one_or_none()
    if r is None:
        raise not_found("Solicitação")
    if r.status != RequestStatus.PENDENTE:
        raise conflict("already_done", "Esta solicitação já foi resolvida.", status=r.status.value)

    if r.type == RequestType.PEDIR_CONTA:
        if not ctx.can(Perm.TABLES_CLOSE):
            raise AppError(403, "forbidden", "A conta é finalizada pelo caixa.")
        await table_svc.close_table(db, ctx, r.table_id, ip)
        return request_out(await load(db, r.id))

    # Atualização condicional: se duas pessoas tocarem ao mesmo tempo, só uma resolve.
    res = await db.execute(
        update(ServiceRequest)
        .where(ServiceRequest.id == r.id, ServiceRequest.status == RequestStatus.PENDENTE)
        .values(status=RequestStatus.CONCLUIDA, completed_at=now(), completed_by_id=ctx.user.id,
                version=ServiceRequest.version + 1)
        .returning(ServiceRequest.id)
    )
    if res.scalar_one_or_none() is None:
        raise conflict("already_done", "Esta solicitação já foi resolvida.")
    r = await load(db, r.id)
    audit(db, establishment_id=ctx.establishment_id, actor_id=ctx.user.id, action=f"request.{r.type.value.lower()}.done",
          target_type="service_request", target_id=r.id, details={"table": r.table.number})
    out = emit_request(db, r)
    table = await db.get(DiningTable, r.table_id)
    assert table is not None
    await table_svc.emit_table(db, table)
    return out
