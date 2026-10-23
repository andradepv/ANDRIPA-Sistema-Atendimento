from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import StaffCtx
from app.core.errors import conflict, not_found
from app.models import Coupon, Promotion
from app.schemas import CouponIn, CouponOut, CouponValidateOut, PromotionIn, PromotionOut
from app.services import coupons as coupon_svc
from app.services.audit import audit
from app.services.events import CUSTOMERS, STAFF, emit


async def list_promotions(db: AsyncSession, est_id: uuid.UUID) -> list[PromotionOut]:
    rows = (await db.execute(select(Promotion).where(Promotion.establishment_id == est_id)
                             .order_by(Promotion.starts_at.desc()))).scalars().all()
    return [PromotionOut.model_validate(p) for p in rows]


async def active_promotions(db: AsyncSession, est_id: uuid.UUID) -> list[PromotionOut]:
    """Somente promoções ativas e dentro do período de validade."""
    now = datetime.now(UTC)
    rows = (await db.execute(select(Promotion).where(
        Promotion.establishment_id == est_id, Promotion.active.is_(True),
        Promotion.starts_at <= now, Promotion.ends_at > now).order_by(Promotion.ends_at))).scalars().all()
    return [PromotionOut.model_validate(p) for p in rows]


async def save_promotion(db: AsyncSession, ctx: StaffCtx, data: PromotionIn,
                         promo_id: uuid.UUID | None = None) -> PromotionOut:
    if promo_id:
        p = (await db.execute(select(Promotion).where(Promotion.id == promo_id,
                                                      Promotion.establishment_id == ctx.establishment_id))).scalar_one_or_none()
        if p is None:
            raise not_found("Promoção")
        for k, v in data.model_dump().items():
            setattr(p, k, v)
    else:
        p = Promotion(establishment_id=ctx.establishment_id, **data.model_dump())
        db.add(p)
    await db.flush()
    await db.refresh(p)
    audit(db, establishment_id=ctx.establishment_id, actor_id=ctx.user.id,
          action="promotion.update" if promo_id else "promotion.create", target_type="promotion", target_id=p.id,
          details={"title": p.title})
    emit(db, ctx.establishment_id, "promotions.updated", {}, audience=(STAFF, CUSTOMERS))
    return PromotionOut.model_validate(p)


async def list_coupons(db: AsyncSession, est_id: uuid.UUID) -> list[CouponOut]:
    rows = (await db.execute(select(Coupon).where(Coupon.establishment_id == est_id)
                             .order_by(Coupon.created_at.desc()))).scalars().all()
    return [CouponOut.model_validate(c) for c in rows]


async def save_coupon(db: AsyncSession, ctx: StaffCtx, data: CouponIn, coupon_id: uuid.UUID | None = None) -> CouponOut:
    if coupon_id:
        c = (await db.execute(select(Coupon).where(Coupon.id == coupon_id,
                                                   Coupon.establishment_id == ctx.establishment_id))).scalar_one_or_none()
        if c is None:
            raise not_found("Cupom")
        if data.max_uses is not None and data.max_uses < c.uses_count:
            raise conflict("max_uses_below_count", "Limite menor que a quantidade já utilizada.")
        for k, v in data.model_dump().items():
            setattr(c, k, v)
    else:
        c = Coupon(establishment_id=ctx.establishment_id, uses_count=0, **data.model_dump())
        db.add(c)
    try:
        await db.flush()
    except IntegrityError as e:
        raise conflict("coupon_exists", "Já existe um cupom com esse código.") from e
    await db.refresh(c)
    audit(db, establishment_id=ctx.establishment_id, actor_id=ctx.user.id,
          action="coupon.update" if coupon_id else "coupon.create", target_type="coupon", target_id=c.id,
          details={"code": c.code})
    return CouponOut.model_validate(c)


async def validate_coupon(db: AsyncSession, est_id: uuid.UUID, code: str, subtotal: int | None) -> CouponValidateOut:
    c = await coupon_svc.find(db, est_id, code)
    reason = coupon_svc.invalid_reason(c, subtotal)
    if reason or c is None:
        return CouponValidateOut(valid=False, code=code, reason=reason)
    return CouponValidateOut(
        valid=True, code=c.code, description=c.description, discount_type=c.discount_type, value=c.value,
        min_order_cents=c.min_order_cents,
        estimated_discount_cents=coupon_svc.compute_discount(c, subtotal) if subtotal is not None else None,
    )
