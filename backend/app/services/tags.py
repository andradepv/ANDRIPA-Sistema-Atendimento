"""Provisionamento de etiquetas NFC: o servidor cria a mesa, gera a URL e acompanha a gravação.

Ninguém digita a URL: o celular do administrador recebe do servidor exatamente o que deve gravar, lê de volta
e devolve o resultado, que é conferido aqui. Cada passo vira um evento `tag.updated` (tempo real) e auditoria.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import StaffCtx
from app.core.errors import AppError, conflict, not_found
from app.core.security import new_public_code
from app.domain.states import (
    LIVE_TAG_STATUSES,
    TAG_TRANSITIONS,
    TableStatus,
    TagStatus,
    ensure_transition,
)
from app.models import DiningTable, TableTag
from app.schemas import ProvisionIn, ProvisionOut, TableCreate, TagOut, TagStartIn, TagWrittenIn
from app.services import tables as table_svc
from app.services.audit import audit
from app.services.events import STAFF, emit
from app.services.serializers import public_url, table_out, tag_out

LOCK_WINDOW = timedelta(minutes=2)  # tempo para travar depois da autorização com senha


def _now() -> datetime:
    return datetime.now(UTC)


def normalize_uid(uid: str) -> str:
    return uid.replace(":", "").upper()


def _norm_url(u: str) -> str:
    return u.strip().rstrip("/").lower()


async def _load(db: AsyncSession, est_id: uuid.UUID, tag_id: uuid.UUID, *, lock: bool = True) -> TableTag:
    q = (
        select(TableTag)
        .where(TableTag.id == tag_id, TableTag.establishment_id == est_id)
        .execution_options(populate_existing=True)
    )
    if lock:
        q = q.with_for_update(of=TableTag)
    g = (await db.execute(q)).unique().scalar_one_or_none()
    if g is None:
        raise not_found("Etiqueta")
    return g


async def _emit(db: AsyncSession, g: TableTag) -> TagOut:
    await db.flush()
    await db.refresh(g)
    out = tag_out(g)
    emit(db, g.establishment_id, "tag.updated", {"tag": out.model_dump(mode="json")}, audience=(STAFF,))
    return out


def _move(g: TableTag, target: TagStatus, *, error: str | None = None) -> None:
    ensure_transition(TAG_TRANSITIONS, g.status, target, "Etiqueta")
    g.status = target
    g.error = error
    g.version += 1


async def _new_attempt(db: AsyncSession, ctx: StaffCtx, t: DiningTable) -> TableTag:
    g = TableTag(
        establishment_id=t.establishment_id,
        table_id=t.id,
        status=TagStatus.PENDENTE,
        url=public_url(t),
        started_by_id=ctx.user.id,
    )
    db.add(g)
    try:
        await db.flush()
    except IntegrityError as e:  # índice único parcial: uma etiqueta viva por mesa
        raise conflict("tag_in_progress", "Já existe uma etiqueta em andamento para esta mesa.") from e
    return g


async def provision_table(db: AsyncSession, ctx: StaffCtx, data: ProvisionIn, ip: str | None) -> ProvisionOut:
    """Cria a mesa (código, QR, posição na planta) e abre a gravação da etiqueta, tudo numa transação."""
    await table_svc.confirm_identity(
        db, ctx, data.confirm_secret, action="tag.confirm_denied", target_type="table", target_id=None, ip=ip
    )
    await table_svc.create_table(db, ctx, TableCreate(number=data.number, name=data.name))
    t = (
        await db.execute(
            select(DiningTable)
            .where(DiningTable.establishment_id == ctx.establishment_id, DiningTable.number == data.number)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    g = await _new_attempt(db, ctx, t)
    audit(
        db,
        establishment_id=ctx.establishment_id,
        actor_id=ctx.user.id,
        action="tag.provision",
        target_type="table_tag",
        target_id=g.id,
        details={"table": t.number},
        ip=ip,
    )
    tag = await _emit(db, g)
    return ProvisionOut(table=await table_out(db, t), tag=tag, qr_svg_url=f"/api/v1/tables/{t.id}/qr.svg")


async def start_tag(db: AsyncSession, ctx: StaffCtx, table_id: uuid.UUID, data: TagStartIn, ip: str | None) -> TagOut:
    """Abre (ou reabre) a gravação da etiqueta de uma mesa existente."""
    await table_svc.confirm_identity(
        db, ctx, data.confirm_secret, action="tag.confirm_denied", target_type="table", target_id=table_id, ip=ip
    )
    t = await table_svc.get_table(db, ctx.establishment_id, table_id, lock=True)
    if not t.active:
        raise conflict("table_inactive", "Mesa desativada.")
    live = (
        (
            await db.execute(
                select(TableTag)
                .where(TableTag.table_id == t.id, TableTag.status.in_(LIVE_TAG_STATUSES))
                .with_for_update(of=TableTag)
                .execution_options(populate_existing=True)
            )
        )
        .unique()
        .scalar_one_or_none()
    )
    if live is not None:
        if live.status in (TagStatus.GRAVADA, TagStatus.TRAVADA):
            if not data.replace:
                raise conflict(
                    "tag_exists",
                    f"A mesa {t.number} já tem etiqueta {live.status.value.lower()}. "
                    "Confirme a substituição para gravar outra.",
                    status=live.status.value,
                )
            if t.status != TableStatus.LIVRE:
                raise conflict("table_in_use", "Feche a mesa antes de substituir a etiqueta.")
            # A etiqueta antiga pode continuar existindo (uma travada não se apaga): o endereço muda,
            # e a etiqueta/QR antigos deixam de funcionar.
            t.public_code = new_public_code()
            t.version += 1
        _move(live, TagStatus.SUBSTITUIDA)
        await _emit(db, live)
    g = await _new_attempt(db, ctx, t)
    audit(
        db,
        establishment_id=ctx.establishment_id,
        actor_id=ctx.user.id,
        action="tag.start",
        target_type="table_tag",
        target_id=g.id,
        details={"table": t.number, "replace": data.replace},
        ip=ip,
    )
    if live is not None and live.status == TagStatus.SUBSTITUIDA and data.replace:
        await table_svc.emit_table(db, t)
    return await _emit(db, g)


async def list_tags(db: AsyncSession, est_id: uuid.UUID) -> list[TagOut]:
    since = _now() - timedelta(hours=24)
    rows = (
        (
            await db.execute(
                select(TableTag)
                .where(
                    TableTag.establishment_id == est_id,
                    TableTag.status != TagStatus.SUBSTITUIDA,
                    (TableTag.status.in_(LIVE_TAG_STATUSES)) | (TableTag.updated_at >= since),
                )
                .order_by(TableTag.updated_at.desc())
                .limit(500)
                .execution_options(populate_existing=True)
            )
        )
        .unique()
        .scalars()
        .all()
    )
    return [tag_out(g) for g in rows]


async def mark_writing(db: AsyncSession, ctx: StaffCtx, tag_id: uuid.UUID) -> TagOut:
    g = await _load(db, ctx.establishment_id, tag_id)
    _move(g, TagStatus.GRAVANDO)
    try:
        return await _emit(db, g)
    except IntegrityError as e:  # retomar uma falha antiga enquanto já existe outra tentativa viva
        raise conflict("tag_in_progress", "Já existe uma etiqueta em andamento para esta mesa.") from e


async def mark_written(
    db: AsyncSession, ctx: StaffCtx, tag_id: uuid.UUID, data: TagWrittenIn, ip: str | None
) -> TagOut:
    g = await _load(db, ctx.establishment_id, tag_id)
    if g.status != TagStatus.GRAVANDO:
        ensure_transition(TAG_TRANSITIONS, g.status, TagStatus.GRAVADA, "Etiqueta")
    uid = normalize_uid(data.uid)
    t = await table_svc.get_table(db, ctx.establishment_id, g.table_id)

    problem: tuple[str, str, int] | None = None
    if _norm_url(data.read_url) != _norm_url(g.url):
        problem = ("tag_url_mismatch", "A URL lida na etiqueta é diferente da esperada. Grave novamente.", 422)
    elif _norm_url(g.url) != _norm_url(public_url(t)):
        problem = ("tag_url_stale", "O endereço da mesa mudou durante a gravação. Inicie uma nova gravação.", 409)
    else:
        other = (
            (
                await db.execute(
                    select(TableTag).where(
                        TableTag.establishment_id == ctx.establishment_id,
                        TableTag.uid == uid,
                        TableTag.id != g.id,
                        TableTag.status.in_((TagStatus.GRAVADA, TagStatus.TRAVADA)),
                    )
                )
            )
            .unique()
            .scalar_one_or_none()
        )
        if other is not None:
            problem = ("tag_uid_in_use", f"Esta etiqueta física já está em uso na mesa {other.table.number}.", 409)
    if problem is not None:
        code, msg, status = problem
        _move(g, TagStatus.FALHA, error=msg)
        audit(
            db,
            establishment_id=ctx.establishment_id,
            actor_id=ctx.user.id,
            action="tag.write_failed",
            target_type="table_tag",
            target_id=g.id,
            details={"table": t.number, "code": code},
            ip=ip,
        )
        await _emit(db, g)
        await db.commit()  # a falha precisa ficar registrada mesmo devolvendo erro
        raise AppError(status, code, msg)

    g.uid = uid
    g.written_at = _now()
    _move(g, TagStatus.GRAVADA)
    try:
        out = await _emit(db, g)
    except IntegrityError as e:  # corrida: outro administrador gravou o mesmo chip neste instante
        raise conflict("tag_uid_in_use", "Esta etiqueta física já está em uso em outra mesa.") from e
    audit(
        db,
        establishment_id=ctx.establishment_id,
        actor_id=ctx.user.id,
        action="tag.written",
        target_type="table_tag",
        target_id=g.id,
        details={"table": t.number, "uid": uid},
        ip=ip,
    )
    return out


async def mark_failed(db: AsyncSession, ctx: StaffCtx, tag_id: uuid.UUID, reason: str) -> TagOut:
    g = await _load(db, ctx.establishment_id, tag_id)
    _move(g, TagStatus.FALHA, error=reason)
    audit(
        db,
        establishment_id=ctx.establishment_id,
        actor_id=ctx.user.id,
        action="tag.failed",
        target_type="table_tag",
        target_id=g.id,
        details={"reason": reason},
    )
    return await _emit(db, g)


async def authorize_lock(db: AsyncSession, ctx: StaffCtx, tag_id: uuid.UUID, secret: str, ip: str | None) -> TagOut:
    """Travar é irreversível: exige a senha/PIN do administrador, e só vale por alguns minutos."""
    await table_svc.confirm_identity(
        db, ctx, secret, action="tag.confirm_denied", target_type="table_tag", target_id=tag_id, ip=ip
    )
    g = await _load(db, ctx.establishment_id, tag_id)
    if g.status != TagStatus.GRAVADA:
        raise conflict("tag_not_ready", "Só é possível travar uma etiqueta gravada e conferida.", status=g.status.value)
    g.lock_authorized_at = _now()
    g.version += 1
    audit(
        db,
        establishment_id=ctx.establishment_id,
        actor_id=ctx.user.id,
        action="tag.lock_authorized",
        target_type="table_tag",
        target_id=g.id,
        ip=ip,
    )
    return await _emit(db, g)


async def mark_locked(db: AsyncSession, ctx: StaffCtx, tag_id: uuid.UUID, ip: str | None) -> TagOut:
    g = await _load(db, ctx.establishment_id, tag_id)
    if g.status != TagStatus.GRAVADA:
        raise conflict("tag_not_ready", "Só é possível travar uma etiqueta gravada e conferida.", status=g.status.value)
    if g.lock_authorized_at is None or _now() - g.lock_authorized_at > LOCK_WINDOW:
        raise conflict("lock_not_authorized", "Confirme a senha para travar a etiqueta.")
    _move(g, TagStatus.TRAVADA)
    g.locked_at = _now()
    audit(
        db,
        establishment_id=ctx.establishment_id,
        actor_id=ctx.user.id,
        action="tag.locked",
        target_type="table_tag",
        target_id=g.id,
        details={"uid": g.uid},
        ip=ip,
    )
    return await _emit(db, g)
