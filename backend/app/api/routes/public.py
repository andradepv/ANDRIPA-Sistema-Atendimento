"""Endpoints do cliente (QR Code / NFC). Sem conta: autorização por token de sessão da mesa."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CustomerCtx, get_customer
from app.core.config import get_settings
from app.core.ratelimit import client_ip, hit
from app.db.session import get_db
from app.schemas import (
    CouponValidateIn,
    CouponValidateOut,
    CustomerRequestIn,
    CustomerSessionOut,
    JoinIn,
    JoinOut,
    MenuCategoryOut,
    OrderIn,
    OrderOut,
    PromotionOut,
    PublicTableOut,
    PushSubscribeIn,
    PushUnsubscribeIn,
    ServiceRequestOut,
)
from app.services import customer as svc
from app.services import menu as menu_svc
from app.services import orders as order_svc
from app.services import promotions as promo_svc
from app.services import push as push_svc
from app.services import requests as req_svc
from app.services.idempotency import run_idempotent
from app.services.tables import session_totals

router = APIRouter(prefix="/public", tags=["public"])


@router.get("/tables/{code}", response_model=PublicTableOut)
async def public_table(code: str, request: Request, db: AsyncSession = Depends(get_db)) -> PublicTableOut:
    await hit(f"pub:ip:{client_ip(request)}", 120, 60)
    return await svc.public_table(db, code)


@router.post("/tables/{code}/join", response_model=JoinOut)
async def join(code: str, data: JoinIn, request: Request, db: AsyncSession = Depends(get_db)) -> JoinOut:
    ip = client_ip(request)
    await hit(f"join:ip:{ip}", 30, 60)
    return await svc.join(db, code, data, ip)


@router.get("/session", response_model=CustomerSessionOut)
async def session_state(ctx: CustomerCtx = Depends(get_customer), db: AsyncSession = Depends(get_db)) -> CustomerSessionOut:
    return await svc.session_state(db, ctx)


@router.get("/menu", response_model=list[MenuCategoryOut])
async def menu(ctx: CustomerCtx = Depends(get_customer), db: AsyncSession = Depends(get_db)) -> list[MenuCategoryOut]:
    return await menu_svc.public_menu(db, ctx.establishment.id)


async def _customer_limits(ctx: CustomerCtx, request: Request) -> None:
    await hit(f"cust:session:{ctx.session.id}", 40, 60)
    await hit(f"cust:token:{ctx.token.id}", 20, 60)
    await hit(f"cust:ip:{client_ip(request)}", 60, 60)


@router.post("/service-requests", response_model=ServiceRequestOut, status_code=201)
async def create_request(data: CustomerRequestIn, request: Request,
                         idempotency_key: str | None = Header(default=None),
                         ctx: CustomerCtx = Depends(get_customer), db: AsyncSession = Depends(get_db)) -> Response:
    await _customer_limits(ctx, request)
    return await run_idempotent(db, scope=f"req:{ctx.session.id}", key=idempotency_key, request_body=data,
                                status_code=201, action=lambda: req_svc.customer_create(db, ctx, data.type, data.note))


@router.post("/service-requests/{request_id}/cancel", response_model=ServiceRequestOut)
async def cancel_request(request_id: uuid.UUID, request: Request, ctx: CustomerCtx = Depends(get_customer),
                         db: AsyncSession = Depends(get_db)) -> ServiceRequestOut:
    await _customer_limits(ctx, request)
    out = await req_svc.customer_cancel(db, ctx, request_id)
    await db.commit()
    return out


@router.post("/orders", response_model=OrderOut, status_code=201)
async def create_order(data: OrderIn, request: Request, idempotency_key: str | None = Header(default=None),
                       ctx: CustomerCtx = Depends(get_customer), db: AsyncSession = Depends(get_db)) -> Response:
    await _customer_limits(ctx, request)
    await hit(f"cust:orders:{ctx.session.id}", 15, 300)
    return await run_idempotent(db, scope=f"order:{ctx.session.id}", key=idempotency_key, request_body=data,
                                status_code=201, action=lambda: order_svc.create_customer_order(db, ctx, data))


@router.get("/promotions", response_model=list[PromotionOut])
async def promotions(ctx: CustomerCtx = Depends(get_customer), db: AsyncSession = Depends(get_db)) -> list[PromotionOut]:
    return await promo_svc.active_promotions(db, ctx.establishment.id)


@router.post("/coupons/validate", response_model=CouponValidateOut)
async def validate_coupon(data: CouponValidateIn, request: Request, ctx: CustomerCtx = Depends(get_customer),
                          db: AsyncSession = Depends(get_db)) -> CouponValidateOut:
    await hit(f"coupon:session:{ctx.session.id}", 10, 300)
    await hit(f"coupon:ip:{client_ip(request)}", 20, 300)
    subtotal, _ = await session_totals(db, ctx.session.id)
    return await promo_svc.validate_coupon(db, ctx.establishment.id, data.code, subtotal)


@router.get("/push/config")
async def push_config() -> dict[str, object]:
    s = get_settings()
    return {"enabled": s.push_enabled, "public_key": s.vapid_public_key if s.push_enabled else None}


@router.post("/push/subscribe", status_code=204)
async def push_subscribe(data: PushSubscribeIn, request: Request, ctx: CustomerCtx = Depends(get_customer),
                         db: AsyncSession = Depends(get_db)) -> Response:
    await hit(f"push:ip:{client_ip(request)}", 10, 600)
    await push_svc.subscribe(db, ctx.establishment.id, data)
    return Response(status_code=204)


@router.post("/push/unsubscribe", status_code=204)
async def push_unsubscribe(data: PushUnsubscribeIn, request: Request, db: AsyncSession = Depends(get_db)) -> Response:
    # Cancelamento não exige sessão ativa: o cliente pode sair a qualquer momento.
    await hit(f"push:ip:{client_ip(request)}", 10, 600)
    await push_svc.unsubscribe(db, data.endpoint)
    return Response(status_code=204)
