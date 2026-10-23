from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models import Coupon, DiscountType


def compute_discount(c: Coupon, subtotal_cents: int) -> int:
    if c.discount_type == DiscountType.PERCENT:
        d = subtotal_cents * c.value // 100
    else:
        d = c.value
    return max(0, min(d, subtotal_cents))


def invalid_reason(c: Coupon | None, subtotal_cents: int | None, at: datetime | None = None) -> str | None:
    at = at or datetime.now(UTC)
    if c is None or not c.active:
        return "Cupom inexistente ou inativo."
    if at < c.starts_at:
        return "Cupom ainda não está vigente."
    if at >= c.ends_at:
        return "Cupom expirado."
    if c.max_uses is not None and c.uses_count >= c.max_uses:
        return "Cupom esgotado."
    if subtotal_cents is not None and subtotal_cents < c.min_order_cents:
        return "Valor mínimo da conta não atingido."
    return None


async def find(db: AsyncSession, est_id: uuid.UUID, code: str) -> Coupon | None:
    return (await db.execute(select(Coupon).where(
        Coupon.establishment_id == est_id, Coupon.code == code.strip().upper()))).scalar_one_or_none()


async def redeem(db: AsyncSession, est_id: uuid.UUID, code: str, subtotal_cents: int) -> Coupon:
    """Aplica o cupom de forma atômica (limite de uso garantido por UPDATE condicional)."""
    c = await find(db, est_id, code)
    reason = invalid_reason(c, subtotal_cents)
    if reason:
        raise AppError(422, "coupon_invalid", reason)
    assert c is not None
    res = await db.execute(
        update(Coupon)
        .where(Coupon.id == c.id, (Coupon.max_uses.is_(None)) | (Coupon.uses_count < Coupon.max_uses))
        .values(uses_count=Coupon.uses_count + 1)
        .returning(Coupon.id)
    )
    if res.scalar_one_or_none() is None:
        raise AppError(422, "coupon_invalid", "Cupom esgotado.")
    await db.refresh(c)
    return c
