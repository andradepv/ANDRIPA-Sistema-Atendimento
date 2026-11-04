"""Endpoints do cliente (QR Code / NFC). Sem conta: autorização por token de sessão da mesa."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CustomerCtx, get_customer
from app.core.ratelimit import client_ip, hit
from app.db.session import get_db
from app.schemas import CustomerRequestIn, CustomerSessionOut, JoinIn, JoinOut, PublicTableOut, ServiceRequestOut
from app.services import customer as svc
from app.services import requests as req_svc
from app.services.idempotency import run_idempotent

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
