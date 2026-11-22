from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import StaffCtx
from app.core.errors import AppError, conflict, not_found
from app.core.ratelimit import hit
from app.core.security import new_public_code, verify_secret
from app.domain.states import RequestStatus, RequestType, SessionStatus, TableStatus
from app.models import CustomerToken, DiningTable, ServiceRequest, TableSession, User
from app.schemas import SessionDetailOut, SessionHistoryOut, TableCreate, TableOut, TablePatch
from app.services import layouts as layout_svc
from app.services.audit import audit
from app.services.events import SESSION, STAFF, emit
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
    t = DiningTable(
        establishment_id=ctx.establishment_id,
        number=data.number,
        name=data.name or None,
        public_code=new_public_code(),
        status=TableStatus.LIVRE,
    )
    db.add(t)
    try:
        await db.flush()
    except IntegrityError as e:
        raise conflict("table_number_taken", f"Já existe a mesa {data.number}.") from e
    audit(
        db,
        establishment_id=ctx.establishment_id,
        actor_id=ctx.user.id,
        action="table.create",
        target_type="table",
        target_id=t.id,
        details={"number": data.number},
    )
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
    audit(
        db,
        establishment_id=ctx.establishment_id,
        actor_id=ctx.user.id,
        action="table.update",
        target_type="table",
        target_id=t.id,
        details=changes,
    )
    return await emit_table(db, t)


async def rotate_code(db: AsyncSession, ctx: StaffCtx, table_id: uuid.UUID) -> TableOut:
    t = await get_table(db, ctx.establishment_id, table_id, lock=True)
    if t.status != TableStatus.LIVRE:
        raise conflict("table_in_use", "Gere um novo código apenas com a mesa livre.")
    t.public_code = new_public_code()
    t.version += 1
    audit(
        db,
        establishment_id=ctx.establishment_id,
        actor_id=ctx.user.id,
        action="table.rotate_code",
        target_type="table",
        target_id=t.id,
    )
    return await emit_table(db, t)


# ---------- liberar mesa ----------
# ---------- liberar mesa ----------
async def _open(
    db: AsyncSession, est_id: uuid.UUID, table_id: uuid.UUID, user: User, ip: str | None, via: str
) -> TableOut:
    t = await get_table(db, est_id, table_id, lock=True)
    if not t.active:
        raise conflict("table_inactive", "Mesa desativada.")
    if t.status not in (TableStatus.LIVRE, TableStatus.AGUARDANDO_LIBERACAO):
        raise conflict("table_not_free", f"A mesa {t.number} já está liberada.")

    s = TableSession(
        establishment_id=t.establishment_id, table_id=t.id, status=SessionStatus.OPEN, opened_by_id=user.id
    )
    db.add(s)
    try:
        await db.flush()
    except IntegrityError as e:  # índice único parcial: proteção final contra sessão dupla
        raise conflict("table_not_free", f"A mesa {t.number} já está liberada.") from e

    # Conclui automaticamente qualquer solicitação pendente de liberação desta mesa
    unlock_reqs = (
        (
            await db.execute(
                select(ServiceRequest)
                .where(
                    ServiceRequest.table_id == t.id,
                    ServiceRequest.type == RequestType.LIBERAR_MESA,
                    ServiceRequest.status == RequestStatus.PENDENTE,
                )
                .with_for_update(of=ServiceRequest)
                .execution_options(populate_existing=True)
            )
        )
        .unique()
        .scalars()
        .all()
    )
    ts = now()
    for r in unlock_reqs:
        r.session_id = s.id
        r.status = RequestStatus.CONCLUIDA
        r.completed_at = ts
        r.completed_by_id = user.id
        r.version += 1

    t.status = TableStatus.OCUPADA
    t.current_session_id = s.id
    t.version += 1
    await db.flush()

    for r in unlock_reqs:
        r2 = (
            (
                await db.execute(
                    select(ServiceRequest).where(ServiceRequest.id == r.id).execution_options(populate_existing=True)
                )
            )
            .unique()
            .scalar_one()
        )
        emit(db, t.establishment_id, "request.updated", {"request": request_out(r2).model_dump(mode="json")})

    audit(
        db,
        establishment_id=est_id,
        actor_id=user.id,
        action="table.open",
        target_type="table_session",
        target_id=s.id,
        details={"table": t.number, "via": via},
        ip=ip,
    )
    return await emit_table(db, t)


async def staff_open(db: AsyncSession, ctx: StaffCtx, table_id: uuid.UUID, ip: str | None) -> TableOut:
    return await _open(db, ctx.establishment_id, table_id, ctx.user, ip, "painel")


async def find_user_by_pin(
    db: AsyncSession, est_id: uuid.UUID, pin: str, *, exclude: uuid.UUID | None = None
) -> User | None:
    """O PIN é único por estabelecimento; compara com o hash de cada pessoa ativa da equipe."""
    q = select(User).where(User.establishment_id == est_id, User.active.is_(True))
    if exclude:
        q = q.where(User.id != exclude)
    users = (await db.execute(q)).scalars().all()

    def _match() -> User | None:
        return next((u for u in users if verify_secret(pin, u.pin_hash)), None)

    # Argon2 é pesado: roda fora do event loop.
    return await asyncio.to_thread(_match)


async def public_open(db: AsyncSession, t: DiningTable, pin: str, ip: str) -> TableOut:
    """Liberação pela página da mesa: basta o PIN de alguém da equipe."""
    if t.status not in (TableStatus.LIVRE, TableStatus.AGUARDANDO_LIBERACAO):
        raise conflict("table_not_free", f"A mesa {t.number} já está liberada.")
    await hit(f"pinopen:ip:{ip}", 10, 600)
    await hit(f"pinopen:table:{t.id}", 10, 600)
    await hit(f"pinopen:est:{t.establishment_id}", 40, 600)
    user = await find_user_by_pin(db, t.establishment_id, pin)
    if user is None:
        audit(
            db,
            establishment_id=t.establishment_id,
            actor_kind="CLIENTE",
            action="table.open_denied",
            target_type="table",
            target_id=t.id,
            details={"table": t.number},
            ip=ip,
        )
        await db.commit()
        raise AppError(403, "invalid_pin", "PIN incorreto.")
    return await _open(db, t.establishment_id, t.id, user, ip, "pagina_da_mesa")


# ---------- encerrar mesa (conta finalizada) ----------
async def close_table(db: AsyncSession, ctx: StaffCtx, table_id: uuid.UUID, ip: str | None) -> TableOut:
    # Ordem de bloqueio fixa (mesa → sessão → solicitações) para evitar deadlocks.
    t = await get_table(db, ctx.establishment_id, table_id, lock=True)
    if t.current_session_id is None:
        raise conflict("table_not_open", f"A mesa {t.number} não está liberada.")
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
    ts = now()
    s.status = SessionStatus.CLOSED
    s.closed_at = ts
    s.closed_by_id = ctx.user.id

    # Revoga todas as credenciais do cliente desta sessão.
    await db.execute(
        update(CustomerToken)
        .where(CustomerToken.session_id == s.id, CustomerToken.revoked_at.is_(None))
        .values(revoked_at=ts)
    )
    pending = (
        (
            await db.execute(
                select(ServiceRequest)
                .where(ServiceRequest.session_id == s.id, ServiceRequest.status == RequestStatus.PENDENTE)
                .with_for_update(of=ServiceRequest)
                .execution_options(populate_existing=True)
            )
        )
        .unique()
        .scalars()
        .all()
    )
    for r in pending:
        # A conta pedida é finalizada; o que ficou sem resposta é dado como cancelado.
        r.status = RequestStatus.CONCLUIDA if r.type == RequestType.PEDIR_CONTA else RequestStatus.CANCELADA
        r.completed_at = ts
        r.completed_by_id = ctx.user.id
        r.version += 1
    t.status = TableStatus.LIVRE
    t.current_session_id = None
    t.version += 1
    await db.flush()
    for r in pending:
        r2 = (
            (
                await db.execute(
                    select(ServiceRequest).where(ServiceRequest.id == r.id).execution_options(populate_existing=True)
                )
            )
            .unique()
            .scalar_one()
        )
        emit(db, t.establishment_id, "request.updated", {"request": request_out(r2).model_dump(mode="json")})
    emit(
        db,
        t.establishment_id,
        "session.closed",
        {"session_id": str(s.id), "table_id": str(t.id)},
        session_id=s.id,
        audience=(STAFF, SESSION),
    )
    audit(
        db,
        establishment_id=ctx.establishment_id,
        actor_id=ctx.user.id,
        action="session.close",
        target_type="table_session",
        target_id=s.id,
        ip=ip,
        details={"table": t.number},
    )
    return await emit_table(db, t)


# ---------- histórico ----------
async def session_detail(db: AsyncSession, est_id: uuid.UUID, session_id: uuid.UUID) -> SessionDetailOut:
    s = (
        (
            await db.execute(
                select(TableSession).where(TableSession.id == session_id, TableSession.establishment_id == est_id)
            )
        )
        .unique()
        .scalar_one_or_none()
    )
    if s is None:
        raise not_found("Atendimento")
    reqs = (
        (
            await db.execute(
                select(ServiceRequest).where(ServiceRequest.session_id == s.id).order_by(ServiceRequest.created_at)
            )
        )
        .unique()
        .scalars()
        .all()
    )
    closed_by = await db.get(User, s.closed_by_id) if s.closed_by_id else None
    return SessionDetailOut(
        id=s.id,
        table_id=s.table_id,
        table_number=s.table.number,
        table_name=s.table.name,
        status=s.status.value,
        opened_at=s.opened_at,
        opened_by_name=s.opened_by.name,
        closed_at=s.closed_at,
        closed_by_name=closed_by.name if closed_by else None,
        requests=[request_out(r) for r in reqs],
    )


async def history(
    db: AsyncSession, est_id: uuid.UUID, *, table_id: uuid.UUID | None, limit: int, offset: int
) -> tuple[list[SessionHistoryOut], int]:
    q = select(TableSession).where(TableSession.establishment_id == est_id, TableSession.status == SessionStatus.CLOSED)
    if table_id:
        q = q.where(TableSession.table_id == table_id)
    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
    rows = (
        (await db.execute(q.order_by(TableSession.opened_at.desc()).limit(limit).offset(offset)))
        .unique()
        .scalars()
        .all()
    )
    ids = [s.id for s in rows]
    counts: dict[uuid.UUID, int] = {}
    if ids:
        counts = dict(
            (
                await db.execute(
                    select(ServiceRequest.session_id, func.count())
                    .where(ServiceRequest.session_id.in_(ids))
                    .group_by(ServiceRequest.session_id)
                )
            ).all()
        )  # type: ignore[arg-type]
    closer_ids = {s.closed_by_id for s in rows if s.closed_by_id}
    names = (
        {u.id: u.name for u in (await db.execute(select(User).where(User.id.in_(closer_ids)))).scalars()}
        if closer_ids
        else {}
    )
    items = [
        SessionHistoryOut(
            id=s.id,
            table_id=s.table_id,
            table_number=s.table.number,
            opened_at=s.opened_at,
            closed_at=s.closed_at,
            opened_by_name=s.opened_by.name,
            closed_by_name=names.get(s.closed_by_id) if s.closed_by_id else None,
            requests_count=counts.get(s.id, 0),
        )
        for s in rows
    ]
    return items, int(total)


async def confirm_identity(
    db: AsyncSession,
    ctx: StaffCtx,
    secret: str,
    *,
    action: str = "tag.confirm_denied",
    target_type: str | None = None,
    target_id: uuid.UUID | None = None,
    ip: str | None = None,
) -> None:
    """Confirma a identidade do usuário logado (PIN ou senha) para ações sensíveis de provisionamento/NFC."""
    ok = await asyncio.to_thread(verify_secret, secret, ctx.user.pin_hash)
    if not ok:
        audit(
            db,
            establishment_id=ctx.establishment_id,
            actor_id=ctx.user.id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            details={"reason": "invalid_secret"},
            ip=ip,
        )
        await db.commit()
        raise AppError(403, "invalid_secret", "PIN ou senha incorretos.")
