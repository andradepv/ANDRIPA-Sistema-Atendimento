from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import case, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CustomerCtx, StaffCtx
from app.core.errors import AppError, conflict, not_found
from app.domain.states import (
    ACTIVE_REQUEST_STATUSES,
    REQUEST_TRANSITIONS,
    RequestStatus,
    RequestType,
    ensure_transition,
)
from app.models import DiningTable, ServiceRequest
from app.schemas import ServiceRequestOut
from app.services import tables as table_svc
from app.services.audit import audit
from app.services.events import SESSION, STAFF, emit
from app.services.serializers import request_out


def now() -> datetime:
    return datetime.now(UTC)


async def _load(db: AsyncSession, request_id: uuid.UUID) -> ServiceRequest:
    return (await db.execute(select(ServiceRequest).where(ServiceRequest.id == request_id)
                             .execution_options(populate_existing=True))).unique().scalar_one()


def _emit(db: AsyncSession, r: ServiceRequest) -> ServiceRequestOut:
    out = request_out(r)
    emit(db, r.establishment_id, "request.updated", {"request": out.model_dump(mode="json")},
         session_id=r.session_id, audience=(STAFF, SESSION))
    return out


async def customer_create(db: AsyncSession, ctx: CustomerCtx, type_: str, note: str | None) -> ServiceRequestOut:
    rtype = RequestType(type_)
    # Bloqueia a mesa para serializar solicitações da mesma sessão.
    table = (await db.execute(select(DiningTable).where(DiningTable.id == ctx.table.id)
                              .with_for_update().execution_options(populate_existing=True))).scalar_one()
    if table.current_session_id != ctx.session.id:
        raise AppError(401, "session_ended", "Esta sessão da mesa foi encerrada.")
    if rtype == RequestType.PEDIR_CONTA:
        r = await table_svc.request_bill(db, table=table, session=ctx.session, origin="CLIENTE",
                                         actor_id=None, note=note)
        return request_out(r)

    existing = (await db.execute(select(ServiceRequest).where(
        ServiceRequest.session_id == ctx.session.id, ServiceRequest.type == rtype,
        ServiceRequest.status.in_(ACTIVE_REQUEST_STATUSES)))).unique().scalar_one_or_none()
    if existing is not None:
        # Não duplica: devolve o chamado já ativo.
        return request_out(existing)
    r = ServiceRequest(establishment_id=table.establishment_id, session_id=ctx.session.id, table_id=table.id,
                       type=rtype, status=RequestStatus.PENDENTE, note=note, origin="CLIENTE")
    db.add(r)
    try:
        await db.flush()
    except IntegrityError as e:
        raise conflict("request_already_active", "Já existe um chamado ativo.") from e
    r = await _load(db, r.id)
    audit(db, establishment_id=table.establishment_id, actor_kind="CLIENTE", action="request.create",
          target_type="service_request", target_id=r.id, details={"type": rtype.value, "table": table.number})
    out = _emit(db, r)
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
    r = await _load(db, r.id)
    table = await db.get(DiningTable, r.table_id)
    assert table is not None
    out = _emit(db, r)
    await table_svc.emit_table(db, table)
    return out


async def list_requests(db: AsyncSession, est_id: uuid.UUID, *, active_only: bool, limit: int, offset: int,
                        session_id: uuid.UUID | None = None) -> tuple[list[ServiceRequestOut], int]:
    from sqlalchemy import func

    q = select(ServiceRequest).where(ServiceRequest.establishment_id == est_id)
    if active_only:
        q = q.where(ServiceRequest.status.in_(ACTIVE_REQUEST_STATUSES))
    if session_id:
        q = q.where(ServiceRequest.session_id == session_id)
    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
    # Prioridade operacional: pendentes primeiro, maior prioridade, mais antigos.
    status_rank = case((ServiceRequest.status == RequestStatus.PENDENTE, 0),
                       (ServiceRequest.status == RequestStatus.ASSUMIDA, 1),
                       (ServiceRequest.status == RequestStatus.EM_ATENDIMENTO, 2), else_=3)
    q = q.order_by(status_rank, ServiceRequest.priority.desc(), ServiceRequest.created_at).limit(limit).offset(offset)
    rows = (await db.execute(q)).unique().scalars().all()
    return [request_out(r) for r in rows], int(total)


async def transition(db: AsyncSession, ctx: StaffCtx, request_id: uuid.UUID, target: RequestStatus) -> ServiceRequestOut:
    r = (await db.execute(select(ServiceRequest).where(
        ServiceRequest.id == request_id, ServiceRequest.establishment_id == ctx.establishment_id)
        .with_for_update(of=ServiceRequest).execution_options(populate_existing=True))).unique().scalar_one_or_none()
    if r is None:
        raise not_found("Chamado")

    if target == RequestStatus.ASSUMIDA:
        # Atualização condicional: só um funcionário consegue assumir.
        res = await db.execute(
            update(ServiceRequest)
            .where(ServiceRequest.id == r.id, ServiceRequest.status == RequestStatus.PENDENTE)
            .values(status=RequestStatus.ASSUMIDA, assigned_to_id=ctx.user.id, claimed_at=now(),
                    version=ServiceRequest.version + 1)
            .returning(ServiceRequest.id)
        )
        if res.scalar_one_or_none() is None:
            r = await _load(db, r.id)
            raise conflict("already_claimed", "Este chamado já foi assumido por outro funcionário.",
                           assigned_to=r.assigned_to.name if r.assigned_to else None, status=r.status.value)
    else:
        ensure_transition(REQUEST_TRANSITIONS, r.status, target, "Chamado")
        if r.assigned_to_id and r.assigned_to_id != ctx.user.id and r.status != RequestStatus.PENDENTE:
            from app.core.permissions import Perm
            if not ctx.can(Perm.REQUESTS_PRIORITIZE):
                raise AppError(403, "not_assignee", "Chamado sob responsabilidade de outro funcionário.")
        if r.type == RequestType.PEDIR_CONTA and target == RequestStatus.CONCLUIDA:
            from app.core.permissions import Perm
            if not ctx.can(Perm.TABLES_CLOSE):
                raise AppError(403, "forbidden", "A conta é concluída pelo caixa ao encerrar a mesa.")
        r.status = target
        if r.assigned_to_id is None:
            r.assigned_to_id = ctx.user.id
            r.claimed_at = now()
        if target in (RequestStatus.CONCLUIDA, RequestStatus.CANCELADA):
            r.completed_at = now()
        r.version += 1
    await db.flush()
    r = await _load(db, r.id)
    audit(db, establishment_id=ctx.establishment_id, actor_id=ctx.user.id, action=f"request.{target.value.lower()}",
          target_type="service_request", target_id=r.id)
    out = _emit(db, r)
    table = await db.get(DiningTable, r.table_id)
    assert table is not None
    await table_svc.emit_table(db, table)
    return out


async def set_priority(db: AsyncSession, ctx: StaffCtx, request_id: uuid.UUID, priority: int) -> ServiceRequestOut:
    r = (await db.execute(select(ServiceRequest).where(
        ServiceRequest.id == request_id, ServiceRequest.establishment_id == ctx.establishment_id)
        .with_for_update(of=ServiceRequest).execution_options(populate_existing=True))).unique().scalar_one_or_none()
    if r is None:
        raise not_found("Chamado")
    if r.status not in ACTIVE_REQUEST_STATUSES:
        raise conflict("request_closed", "Chamado já finalizado.")
    r.priority = priority
    r.version += 1
    await db.flush()
    r = await _load(db, r.id)
    audit(db, establishment_id=ctx.establishment_id, actor_id=ctx.user.id, action="request.priority",
          target_type="service_request", target_id=r.id, details={"priority": priority})
    return _emit(db, r)
