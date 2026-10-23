from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import StaffCtx, require, utcnow
from app.core.errors import AppError, conflict, not_found
from app.core.permissions import Perm, Role
from app.core.security import hash_secret
from app.db.session import get_db
from app.models import AuditLog, Establishment, PushSubscription, StaffSession, User
from app.schemas import (
    AuditOut,
    CouponIn,
    CouponOut,
    EstablishmentOut,
    EstablishmentPatch,
    Page,
    PromotionIn,
    PromotionOut,
    PushBroadcastIn,
    PushBroadcastOut,
    UserCreate,
    UserOut,
    UserPatch,
)
from app.services import promotions as promo_svc
from app.services import push as push_svc
from app.services.audit import audit
from app.services.events import STAFF, emit
from app.services.serializers import user_out

router = APIRouter(prefix="/admin", tags=["admin"])


# ---------- usuários ----------
@router.get("/users", response_model=list[UserOut])
async def list_users(ctx: StaffCtx = Depends(require(Perm.USERS_MANAGE)), db: AsyncSession = Depends(get_db)) -> list[UserOut]:
    rows = (await db.execute(select(User).where(User.establishment_id == ctx.establishment_id)
                             .order_by(User.name))).scalars().all()
    return [user_out(u) for u in rows]


@router.post("/users", response_model=UserOut, status_code=201)
async def create_user(data: UserCreate, ctx: StaffCtx = Depends(require(Perm.USERS_MANAGE)),
                      db: AsyncSession = Depends(get_db)) -> UserOut:
    u = User(establishment_id=ctx.establishment_id, name=data.name, email=data.email, role=data.role,
             password_hash=hash_secret(data.password), pin_hash=hash_secret(data.pin) if data.pin else None)
    db.add(u)
    try:
        await db.flush()
    except IntegrityError as e:
        raise conflict("email_taken", "E-mail já cadastrado.") from e
    audit(db, establishment_id=ctx.establishment_id, actor_id=ctx.user.id, action="user.create",
          target_type="user", target_id=u.id, details={"role": data.role.value, "email": data.email})
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
    if data.password:
        u.password_hash, revoke = hash_secret(data.password), True
    if data.pin:
        u.pin_hash = hash_secret(data.pin)
    if data.clear_pin:
        u.pin_hash = None
    if revoke:  # mudança de papel, desativação ou senha: encerra sessões existentes
        ids = (await db.execute(update(StaffSession).where(StaffSession.user_id == u.id,
                                                           StaffSession.revoked_at.is_(None))
                                .values(revoked_at=utcnow()).returning(StaffSession.id))).scalars().all()
        emit(db, ctx.establishment_id, "staff.session_revoked", {"staff_session_ids": [str(i) for i in ids]},
             audience=())
    audit(db, establishment_id=ctx.establishment_id, actor_id=ctx.user.id, action="user.update",
          target_type="user", target_id=u.id,
          details={k: v for k, v in data.model_dump(exclude_unset=True).items() if k not in ("password", "pin")}
          | {"password_changed": bool(data.password), "pin_changed": bool(data.pin or data.clear_pin)})
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


# ---------- promoções / cupons ----------
@router.get("/promotions", response_model=list[PromotionOut])
async def list_promotions(ctx: StaffCtx = Depends(require(Perm.PROMOTIONS_MANAGE)),
                          db: AsyncSession = Depends(get_db)) -> list[PromotionOut]:
    return await promo_svc.list_promotions(db, ctx.establishment_id)


@router.post("/promotions", response_model=PromotionOut, status_code=201)
async def create_promotion(data: PromotionIn, ctx: StaffCtx = Depends(require(Perm.PROMOTIONS_MANAGE)),
                           db: AsyncSession = Depends(get_db)) -> PromotionOut:
    out = await promo_svc.save_promotion(db, ctx, data)
    await db.commit()
    return out


@router.put("/promotions/{promo_id}", response_model=PromotionOut)
async def update_promotion(promo_id: uuid.UUID, data: PromotionIn,
                           ctx: StaffCtx = Depends(require(Perm.PROMOTIONS_MANAGE)),
                           db: AsyncSession = Depends(get_db)) -> PromotionOut:
    out = await promo_svc.save_promotion(db, ctx, data, promo_id)
    await db.commit()
    return out


@router.get("/coupons", response_model=list[CouponOut])
async def list_coupons(ctx: StaffCtx = Depends(require(Perm.PROMOTIONS_MANAGE)),
                       db: AsyncSession = Depends(get_db)) -> list[CouponOut]:
    return await promo_svc.list_coupons(db, ctx.establishment_id)


@router.post("/coupons", response_model=CouponOut, status_code=201)
async def create_coupon(data: CouponIn, ctx: StaffCtx = Depends(require(Perm.PROMOTIONS_MANAGE)),
                        db: AsyncSession = Depends(get_db)) -> CouponOut:
    out = await promo_svc.save_coupon(db, ctx, data)
    await db.commit()
    return out


@router.put("/coupons/{coupon_id}", response_model=CouponOut)
async def update_coupon(coupon_id: uuid.UUID, data: CouponIn, ctx: StaffCtx = Depends(require(Perm.PROMOTIONS_MANAGE)),
                        db: AsyncSession = Depends(get_db)) -> CouponOut:
    out = await promo_svc.save_coupon(db, ctx, data, coupon_id)
    await db.commit()
    return out


# ---------- push ----------
@router.get("/push/stats")
async def push_stats(ctx: StaffCtx = Depends(require(Perm.PUSH_SEND)), db: AsyncSession = Depends(get_db)) -> dict:
    from app.core.config import get_settings
    n = (await db.execute(select(func.count()).where(
        PushSubscription.establishment_id == ctx.establishment_id, PushSubscription.revoked_at.is_(None),
        PushSubscription.consent_marketing.is_(True)))).scalar_one()
    return {"enabled": get_settings().push_enabled, "subscribers": int(n)}


@router.post("/push/broadcast", response_model=PushBroadcastOut)
async def push_broadcast(data: PushBroadcastIn, ctx: StaffCtx = Depends(require(Perm.PUSH_SEND)),
                         db: AsyncSession = Depends(get_db)) -> PushBroadcastOut:
    from app.core.ratelimit import hit
    await hit(f"broadcast:{ctx.establishment_id}", 5, 3600)
    out = await push_svc.broadcast(db, ctx.establishment_id, data)
    audit(db, establishment_id=ctx.establishment_id, actor_id=ctx.user.id, action="push.broadcast",
          details={"title": data.title, **out.model_dump()})
    await db.commit()
    return out
