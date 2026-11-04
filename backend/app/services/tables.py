from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import StaffCtx
from app.core.errors import AppError, conflict, not_found
from app.core.security import new_join_code, new_public_code, verify_secret
from app.domain.states import (
    ACTIVE_REQUEST_STATUSES,
    TABLE_TRANSITIONS,
    RequestStatus,
    RequestType,
    SessionStatus,
    TableStatus,
    ensure_transition,
)
from app.models import CustomerToken, DiningTable, ServiceRequest, TableSession, User
from app.schemas import (
    CloseSessionIn,
    OpenTableIn,
    SessionDetailOut,
    TableCreate,
    TableOut,
    TablePatch,
)
from app.services import layouts as layout_svc
from app.services.audit import audit
from app.services.events import CUSTOMERS, SESSION, STAFF, emit
from app.services.serializers import request_out, table_out


def now() -> datetime:
    return datetime.now(UTC)


async def get_table(db: AsyncSession, est_id: uuid.UUID, table_id: uuid.UUID, *, lock: bool = False) -> DiningTable:
    q = select(DiningTable).where(DiningTable.id == table_id, DiningTable.establishment_id == est_id)
    if lock:
        q = q.with_for_update().execution_options(populate_existing=True)
    t = (await db.execute(q)).scalar_one_or_none()
    if t is None:
        raise not_found("Mesa")
    return t


async def emit_table(db: AsyncSession, t: DiningTable) -> TableOut:
    await db.flush()
    await db.refresh(t)
    out = await table_out(db, t)
    emit(db, t.establishment_id, "table.updated", {"table": out.model_dump(mode="json")})
    return out


async def create_table(db: AsyncSession, ctx: StaffCtx, data: TableCreate) -> TableOut:
    t = DiningTable(establishment_id=ctx.establishment_id, number=data.number, name=data.name or None,
                    public_code=new_public_code(), status=TableStatus.LIVRE)
    db.add(t)
    try:
        await db.flush()
    except IntegrityError as e:
        raise conflict("table_number_taken", f"Já existe a mesa {data.number}.") from e
    audit(db, establishment_id=ctx.establishment_id, actor_id=ctx.user.id, action="table.create",
          target_type="table", target_id=t.id, details={"number": data.number})
    await layout_svc.auto_place(db, ctx.establishment_id, t.id)
    return await emit_table(db, t)


async def patch_table(db: AsyncSession, ctx: StaffCtx, table_id: uuid.UUID, data: TablePatch) -> TableOut:
    t = await get_table(db, ctx.establishment_id, table_id, lock=True)
    changes = data.model_dump(exclude_unset=True)
    if ("number" in changes and changes["number"] != t.number) or changes.get("active") is False:
        if t.status != TableStatus.LIVRE:
            raise conflict("table_in_use", "Só é possível renumerar ou desativar uma mesa livre.")
    for k, v in changes.items():
        setattr(t, k, v)
    t.version += 1
    try:
        await db.flush()
    except IntegrityError as e:
        raise conflict("table_number_taken", "Já existe uma mesa com esse número.") from e
    audit(db, establishment_id=ctx.establishment_id, actor_id=ctx.user.id, action="table.update",
          target_type="table", target_id=t.id, details=changes)
    return await emit_table(db, t)


async def rotate_code(db: AsyncSession, ctx: StaffCtx, table_id: uuid.UUID) -> TableOut:
    t = await get_table(db, ctx.establishment_id, table_id, lock=True)
    if t.status != TableStatus.LIVRE:
        raise conflict("table_in_use", "Gere um novo código apenas com a mesa livre.")
    t.public_code = new_public_code()
    t.version += 1
    audit(db, establishment_id=ctx.establishment_id, actor_id=ctx.user.id, action="table.rotate_code",
          target_type="table", target_id=t.id)
    return await emit_table(db, t)


async def confirm_identity(db: AsyncSession, ctx: StaffCtx, secret: str, *, action: str, target_type: str,
                           target_id: uuid.UUID | None, ip: str | None) -> None:
    """Confirma quem está operando com credencial individual (PIN pessoal ou senha). Falha vira auditoria."""
    user = await db.get(User, ctx.user.id)
    assert user is not None
    ok = verify_secret(secret, user.pin_hash) if user.pin_hash else False
    if not ok:
        ok = verify_secret(secret, user.password_hash)
    if not ok:
        audit(db, establishment_id=ctx.establishment_id, actor_id=ctx.user.id, action=action,
              target_type=target_type, target_id=target_id, ip=ip)
        await db.commit()
        raise AppError(403, "confirmation_failed", "PIN ou senha de confirmação incorretos.")


async def open_table(db: AsyncSession, ctx: StaffCtx, table_id: uuid.UUID, data: OpenTableIn,
                     ip: str | None) -> TableOut:
    await confirm_identity(db, ctx, data.confirm_secret, action="table.open_denied", target_type="table",
                           target_id=table_id, ip=ip)

    t = await get_table(db, ctx.establishment_id, table_id, lock=True)
    if not t.active:
        raise conflict("table_inactive", "Mesa desativada.")
    if t.status != TableStatus.LIVRE:
        raise conflict("table_not_free", f"A mesa {t.number} já está aberta.", status=t.status.value)
    ensure_transition(TABLE_TRANSITIONS, t.status, TableStatus.OCUPADA, "Mesa")

    s = TableSession(establishment_id=t.establishment_id, table_id=t.id, label=data.label or None,
                     status=SessionStatus.OPEN, join_code=new_join_code(), opened_by_id=ctx.user.id)
    db.add(s)
    try:
        await db.flush()
    except IntegrityError as e:  # índice único parcial: proteção final contra sessão dupla
        raise conflict("table_not_free", f"A mesa {t.number} já está aberta.") from e
    t.status = TableStatus.OCUPADA
    t.current_session_id = s.id
    t.version += 1
    audit(db, establishment_id=ctx.establishment_id, actor_id=ctx.user.id, action="table.open",
          target_type="table_session", target_id=s.id, details={"table": t.number, "label": s.label}, ip=ip)
    return await emit_table(db, t)


async def _active_session(db: AsyncSession, t: DiningTable, *, lock: bool = True) -> TableSession:
    if t.current_session_id is None:
        raise conflict("table_not_open", f"A mesa {t.number} não está aberta.")
    q = select(TableSession).where(TableSession.id == t.current_session_id)
    if lock:
        q = q.with_for_update(of=TableSession).execution_options(populate_existing=True)
    s = (await db.execute(q)).unique().scalar_one()
    if s.status != SessionStatus.OPEN:
        raise conflict("session_closed", "Sessão já encerrada.")
    return s


async def request_bill(db: AsyncSession, *, table: DiningTable, session: TableSession,
                       origin: str, actor_id: uuid.UUID | None, note: str | None) -> ServiceRequest:
    """Registra PEDIR_CONTA e marca a mesa como ENCERRAMENTO_SOLICITADO (não encerra a sessão)."""
    existing = (await db.execute(
        select(ServiceRequest).where(
            ServiceRequest.session_id == session.id, ServiceRequest.type == RequestType.PEDIR_CONTA,
            ServiceRequest.status.in_(ACTIVE_REQUEST_STATUSES),
        )
    )).unique().scalar_one_or_none()
    if existing is not None:
        return existing
    r = ServiceRequest(establishment_id=table.establishment_id, session_id=session.id, table_id=table.id,
                       type=RequestType.PEDIR_CONTA, status=RequestStatus.PENDENTE, note=note,
                       origin=origin, priority=1)
    db.add(r)
    if table.status == TableStatus.OCUPADA:
        ensure_transition(TABLE_TRANSITIONS, table.status, TableStatus.ENCERRAMENTO_SOLICITADO, "Mesa")
        table.status = TableStatus.ENCERRAMENTO_SOLICITADO
        table.version += 1
    session.close_requested_at = session.close_requested_at or now()
    session.version += 1
    await db.flush()
    r = (await db.execute(select(ServiceRequest).where(ServiceRequest.id == r.id)
                          .execution_options(populate_existing=True))).unique().scalar_one()
    audit(db, establishment_id=table.establishment_id, actor_id=actor_id,
          actor_kind="STAFF" if actor_id else "CLIENTE", action="session.request_bill",
          target_type="table_session", target_id=session.id)
    emit(db, table.establishment_id, "request.updated", {"request": request_out(r).model_dump(mode="json")},
         session_id=session.id, audience=(STAFF, SESSION))
    await emit_table(db, table)
    return r


async def staff_request_close(db: AsyncSession, ctx: StaffCtx, table_id: uuid.UUID) -> TableOut:
    t = await get_table(db, ctx.establishment_id, table_id, lock=True)
    s = await _active_session(db, t)
    await request_bill(db, table=t, session=s, origin="FUNCIONARIO", actor_id=ctx.user.id, note=None)
    return await table_out(db, t)


async def cancel_close_request(db: AsyncSession, ctx: StaffCtx, table_id: uuid.UUID) -> TableOut:
    t = await get_table(db, ctx.establishment_id, table_id, lock=True)
    s = await _active_session(db, t)
    ensure_transition(TABLE_TRANSITIONS, t.status, TableStatus.OCUPADA, "Mesa")
    t.status = TableStatus.OCUPADA
    t.version += 1
    s.close_requested_at = None
    s.version += 1
    reqs = (await db.execute(select(ServiceRequest).where(
        ServiceRequest.session_id == s.id, ServiceRequest.type == RequestType.PEDIR_CONTA,
        ServiceRequest.status.in_(ACTIVE_REQUEST_STATUSES)))).unique().scalars().all()
    for r in reqs:
        r.status = RequestStatus.CANCELADA
        r.completed_at = now()
        r.version += 1
    await db.flush()
    for r in reqs:
        await db.refresh(r)
        emit(db, t.establishment_id, "request.updated", {"request": request_out(r).model_dump(mode="json")},
             session_id=s.id, audience=(STAFF, SESSION))
    audit(db, establishment_id=ctx.establishment_id, actor_id=ctx.user.id, action="session.cancel_bill_request",
          target_type="table_session", target_id=s.id)
    return await emit_table(db, t)


async def session_detail(db: AsyncSession, est_id: uuid.UUID, session_id: uuid.UUID) -> SessionDetailOut:
    s = (await db.execute(select(TableSession).where(
        TableSession.id == session_id, TableSession.establishment_id == est_id))).unique().scalar_one_or_none()
    if s is None:
        raise not_found("Sessão")
    reqs = (await db.execute(select(ServiceRequest).where(ServiceRequest.session_id == s.id)
                             .order_by(ServiceRequest.created_at))).unique().scalars().all()
    closed_by = await db.get(User, s.closed_by_id) if s.closed_by_id else None
    return SessionDetailOut(
        id=s.id, table_id=s.table_id, table_number=s.table.number, table_name=s.table.name,
        table_status=s.table.status, label=s.label, status=s.status.value,
        join_code=s.join_code if s.status == SessionStatus.OPEN else None, opened_at=s.opened_at,
        opened_by_name=s.opened_by.name, close_requested_at=s.close_requested_at, closed_at=s.closed_at,
        closed_by_name=closed_by.name if closed_by else None,
        requests=[request_out(r) for r in reqs], version=s.version,
    )


async def close_session(db: AsyncSession, ctx: StaffCtx, session_id: uuid.UUID, data: CloseSessionIn,
                        ip: str | None) -> SessionDetailOut:
    s0 = (await db.execute(select(TableSession.table_id).where(
        TableSession.id == session_id, TableSession.establishment_id == ctx.establishment_id))).scalar_one_or_none()
    if s0 is None:
        raise not_found("Sessão")
    # Ordem de bloqueio fixa (mesa → sessão) para evitar deadlocks.
    t = await get_table(db, ctx.establishment_id, s0, lock=True)
    s = (await db.execute(select(TableSession).where(TableSession.id == session_id)
                          .with_for_update(of=TableSession).execution_options(populate_existing=True))).unique().scalar_one()
    if s.status != SessionStatus.OPEN:
        raise conflict("session_closed", "Esta sessão já foi encerrada.")
    if data.expected_version is not None and data.expected_version != s.version:
        raise conflict("stale_version", "A mesa mudou desde que você abriu o painel. Revise e confirme novamente.",
                       current_version=s.version)

    ts = now()
    s.status = SessionStatus.CLOSED
    s.closed_at = ts
    s.closed_by_id = ctx.user.id
    s.version += 1

    # Revoga todas as credenciais do cliente desta sessão.
    await db.execute(update(CustomerToken).where(CustomerToken.session_id == s.id,
                                                 CustomerToken.revoked_at.is_(None)).values(revoked_at=ts))
    # Encerra chamados ativos: a conta é concluída; os demais ficam cancelados.
    active = (await db.execute(select(ServiceRequest).where(
        ServiceRequest.session_id == s.id, ServiceRequest.status.in_(ACTIVE_REQUEST_STATUSES)))).unique().scalars().all()
    for r in active:
        r.status = RequestStatus.CONCLUIDA if r.type == RequestType.PEDIR_CONTA else RequestStatus.CANCELADA
        r.completed_at = ts
        r.version += 1

    ensure_transition(TABLE_TRANSITIONS, t.status, TableStatus.LIVRE, "Mesa")
    t.status = TableStatus.LIVRE
    t.current_session_id = None
    t.version += 1
    await db.flush()

    for r in active:
        await db.refresh(r)
        emit(db, t.establishment_id, "request.updated", {"request": request_out(r).model_dump(mode="json")})
    emit(db, t.establishment_id, "session.closed", {"session_id": str(s.id), "table_id": str(t.id)},
         session_id=s.id, audience=(STAFF, SESSION))
    audit(db, establishment_id=ctx.establishment_id, actor_id=ctx.user.id, action="session.close",
          target_type="table_session", target_id=s.id, ip=ip,
          details={"table": t.number, "cancelled_requests": len([r for r in active if r.type != RequestType.PEDIR_CONTA])})
    await emit_table(db, t)
    return await session_detail(db, ctx.establishment_id, s.id)


__all__ = ["CUSTOMERS"]
