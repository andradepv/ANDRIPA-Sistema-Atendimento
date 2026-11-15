from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import StaffCtx, require, utcnow
from app.core.errors import AppError, conflict, not_found
from app.core.permissions import Perm, Role
from app.core.security import hash_secret
from app.db.session import get_db
from app.models import AuditLog, Establishment, StaffSession, User
from app.schemas import (
    AuditOut,
    EstablishmentOut,
    EstablishmentPatch,
    NoticeCreatedOut,
    NoticeIn,
    NoticeOut,
    NoticePatch,
    Page,
    PushSubscriptionIn,
    UserCreate,
    UserOut,
    UserPatch,
)
from app.services import notices as notice_svc
from app.services.audit import audit
from app.services.events import STAFF, emit
from app.services.serializers import user_out
from app.services.tables import find_user_by_pin

router = APIRouter(prefix="/admin", tags=["admin"])


# ---------- usuários ----------
def _pin_taken() -> AppError:
    return conflict("pin_taken", "Este PIN já é usado por outra pessoa da equipe. Escolha outro.")


@router.get("/users", response_model=list[UserOut])
async def list_users(ctx: StaffCtx = Depends(require(Perm.USERS_MANAGE)), db: AsyncSession = Depends(get_db)) -> list[UserOut]:
    rows = (await db.execute(select(User).where(User.establishment_id == ctx.establishment_id)
                             .order_by(User.name))).scalars().all()
    return [user_out(u) for u in rows]


@router.post("/users", response_model=UserOut, status_code=201)
async def create_user(data: UserCreate, ctx: StaffCtx = Depends(require(Perm.USERS_MANAGE)),
                      db: AsyncSession = Depends(get_db)) -> UserOut:
    if await find_user_by_pin(db, ctx.establishment_id, data.pin):
        raise _pin_taken()
    u = User(establishment_id=ctx.establishment_id, name=data.name, username=data.username, role=data.role,
             pin_hash=hash_secret(data.pin))
    db.add(u)
    try:
        await db.flush()
    except IntegrityError as e:
        raise conflict("username_taken", "Este usuário já existe. Escolha outro nome de usuário.") from e
    audit(db, establishment_id=ctx.establishment_id, actor_id=ctx.user.id, action="user.create",
          target_type="user", target_id=u.id, details={"role": data.role.value, "username": data.username})
    await db.commit()
    return user_out(u)


@router.patch("/users/{user_id}", response_model=UserOut)
async def patch_user(user_id: uuid.UUID, data: UserPatch, ctx: StaffCtx = Depends(require(Perm.USERS_MANAGE)),
                     db: AsyncSession = Depends(get_db)) -> UserOut:
    u = (await db.execute(select(User).where(User.id == user_id, User.establishment_id == ctx.establishment_id)
                          .with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()
    if u is None:
        raise not_found("Usuário")
    if u.id == ctx.user.id and ((data.role and data.role != Role.ADMIN) or data.active is False):
        raise AppError(422, "cannot_demote_self", "Você não pode remover seu próprio acesso de administrador.")
    if u.role == Role.ADMIN and ((data.role and data.role != Role.ADMIN) or data.active is False):
        admins = (await db.execute(select(func.count()).where(
            User.establishment_id == ctx.establishment_id, User.role == Role.ADMIN, User.active.is_(True)))).scalar_one()
        if admins <= 1:
            raise conflict("last_admin", "É necessário manter pelo menos um administrador ativo.")
    revoke = False
    if data.name is not None:
        u.name = data.name
    if data.role is not None and data.role != u.role:
        u.role, revoke = data.role, True
    if data.active is not None and data.active != u.active:
        u.active = data.active
        revoke = revoke or not data.active
    if data.pin:
        if await find_user_by_pin(db, ctx.establishment_id, data.pin, exclude=u.id):
            raise _pin_taken()
        u.pin_hash, revoke = hash_secret(data.pin), True
    if revoke:  # mudança de papel, desativação ou PIN: encerra sessões existentes
        ids = (await db.execute(update(StaffSession).where(StaffSession.user_id == u.id,
                                                           StaffSession.revoked_at.is_(None))
                                .values(revoked_at=utcnow()).returning(StaffSession.id))).scalars().all()
        emit(db, ctx.establishment_id, "staff.session_revoked", {"staff_session_ids": [str(i) for i in ids]},
             audience=())
    audit(db, establishment_id=ctx.establishment_id, actor_id=ctx.user.id, action="user.update",
          target_type="user", target_id=u.id,
          details={k: v for k, v in data.model_dump(exclude_unset=True).items() if k != "pin"}
          | {"pin_changed": bool(data.pin)})
    await db.commit()
    await db.refresh(u)
    return user_out(u)


# ---------- estabelecimento ----------
@router.get("/establishment", response_model=EstablishmentOut)
async def get_establishment(ctx: StaffCtx = Depends(require(Perm.SETTINGS_MANAGE)),
                            db: AsyncSession = Depends(get_db)) -> EstablishmentOut:
    return EstablishmentOut.model_validate(await db.get(Establishment, ctx.establishment_id))


@router.patch("/establishment", response_model=EstablishmentOut)
async def patch_establishment(data: EstablishmentPatch, ctx: StaffCtx = Depends(require(Perm.SETTINGS_MANAGE)),
                              db: AsyncSession = Depends(get_db)) -> EstablishmentOut:
    est = await db.get(Establishment, ctx.establishment_id)
    assert est is not None
    changes = data.model_dump(exclude_unset=True, exclude_none=True)
    for k, v in changes.items():
        setattr(est, k, v)
    audit(db, establishment_id=ctx.establishment_id, actor_id=ctx.user.id, action="settings.update", details=changes)
    emit(db, ctx.establishment_id, "settings.updated", {}, audience=(STAFF,))
    await db.commit()
    await db.refresh(est)
    return EstablishmentOut.model_validate(est)


# ---------- auditoria ----------
@router.get("/audit-logs", response_model=Page[AuditOut])
async def audit_logs(action: str | None = Query(default=None, max_length=64), limit: int = Query(100, ge=1, le=500),
                     offset: int = Query(0, ge=0), ctx: StaffCtx = Depends(require(Perm.AUDIT_VIEW)),
                     db: AsyncSession = Depends(get_db)) -> Page[AuditOut]:
    q = select(AuditLog).where(AuditLog.establishment_id == ctx.establishment_id)
    if action:
        q = q.where(AuditLog.action.startswith(action))
    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
    rows = (await db.execute(q.order_by(AuditLog.created_at.desc()).limit(limit).offset(offset))).unique().scalars().all()
    return Page(items=[AuditOut(id=a.id, actor_name=a.actor.name if a.actor else None, actor_kind=a.actor_kind,
                                action=a.action, target_type=a.target_type, target_id=a.target_id, details=a.details,
                                created_at=a.created_at) for a in rows],
                total=int(total), limit=limit, offset=offset)


# ---------- avisos aos clientes (com push opcional) ----------
@router.get("/notices", response_model=list[NoticeOut])
async def list_notices(ctx: StaffCtx = Depends(require(Perm.NOTICES_MANAGE)),
                       db: AsyncSession = Depends(get_db)) -> list[NoticeOut]:
    return await notice_svc.list_all(db, ctx.establishment_id)


@router.post("/notices", response_model=NoticeCreatedOut, status_code=201)
async def create_notice(data: NoticeIn, ctx: StaffCtx = Depends(require(Perm.NOTICES_MANAGE)),
                        db: AsyncSession = Depends(get_db)) -> NoticeCreatedOut:
    return await notice_svc.create(db, ctx, data)


@router.patch("/notices/{notice_id}", response_model=NoticeOut)
async def patch_notice(notice_id: uuid.UUID, data: NoticePatch, ctx: StaffCtx = Depends(require(Perm.NOTICES_MANAGE)),
                       db: AsyncSession = Depends(get_db)) -> NoticeOut:
    out = await notice_svc.patch(db, ctx, notice_id, data)
    await db.commit()
    return out


@router.delete("/notices/{notice_id}", status_code=204)
async def delete_notice(notice_id: uuid.UUID, ctx: StaffCtx = Depends(require(Perm.NOTICES_MANAGE)),
                        db: AsyncSession = Depends(get_db)) -> Response:
    await notice_svc.delete(db, ctx, notice_id)
    await db.commit()
    return Response(status_code=204)


@router.get("/push/stats")
async def push_stats(ctx: StaffCtx = Depends(require(Perm.NOTICES_MANAGE)), db: AsyncSession = Depends(get_db)) -> dict:
    from app.core.config import get_settings
    n = (await db.execute(select(func.count()).where(
        PushSubscriptionIn.establishment_id == ctx.establishment_id, PushSubscriptionIn.revoked_at.is_(None),
        PushSubscriptionIn.consent_marketing.is_(True)))).scalar_one()
    return {"enabled": get_settings().push_enabled, "subscribers": int(n)}
