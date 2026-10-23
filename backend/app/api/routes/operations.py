"""Chamados (service requests) e pedidos — lado dos funcionários."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import StaffCtx, require
from app.core.permissions import Perm
from app.db.session import get_db
from app.domain.states import PENDING_ORDER_STATUSES, OrderStatus, RequestStatus
from app.schemas import OrderOut, OrderStatusIn, Page, PriorityIn, ServiceRequestOut
from app.services import orders as order_svc
from app.services import requests as req_svc

router = APIRouter(tags=["operations"])


@router.get("/service-requests", response_model=Page[ServiceRequestOut])
async def list_requests(active: bool = True, session_id: uuid.UUID | None = None,
                        limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0),
                        ctx: StaffCtx = Depends(require(Perm.REQUESTS_VIEW)),
                        db: AsyncSession = Depends(get_db)) -> Page[ServiceRequestOut]:
    items, total = await req_svc.list_requests(db, ctx.establishment_id, active_only=active, limit=limit,
                                               offset=offset, session_id=session_id)
    return Page(items=items, total=total, limit=limit, offset=offset)


def _transition(target: RequestStatus):
    async def handler(request_id: uuid.UUID, ctx: StaffCtx = Depends(require(Perm.REQUESTS_HANDLE)),
                      db: AsyncSession = Depends(get_db)) -> ServiceRequestOut:
        out = await req_svc.transition(db, ctx, request_id, target)
        await db.commit()
        return out
    return handler


router.add_api_route("/service-requests/{request_id}/claim", _transition(RequestStatus.ASSUMIDA),
                     methods=["POST"], response_model=ServiceRequestOut, summary="Assumir chamado")
router.add_api_route("/service-requests/{request_id}/start", _transition(RequestStatus.EM_ATENDIMENTO),
                     methods=["POST"], response_model=ServiceRequestOut, summary="Iniciar atendimento")
router.add_api_route("/service-requests/{request_id}/complete", _transition(RequestStatus.CONCLUIDA),
                     methods=["POST"], response_model=ServiceRequestOut, summary="Concluir chamado")
router.add_api_route("/service-requests/{request_id}/cancel", _transition(RequestStatus.CANCELADA),
                     methods=["POST"], response_model=ServiceRequestOut, summary="Cancelar chamado")


@router.post("/service-requests/{request_id}/priority", response_model=ServiceRequestOut)
async def set_priority(request_id: uuid.UUID, data: PriorityIn,
                       ctx: StaffCtx = Depends(require(Perm.REQUESTS_PRIORITIZE)),
                       db: AsyncSession = Depends(get_db)) -> ServiceRequestOut:
    out = await req_svc.set_priority(db, ctx, request_id, data.priority)
    await db.commit()
    return out


@router.get("/orders", response_model=Page[OrderOut])
async def list_orders(status: list[OrderStatus] = Query(default=[]), active: bool = False,
                      session_id: uuid.UUID | None = None, limit: int = Query(100, ge=1, le=500),
                      offset: int = Query(0, ge=0), ctx: StaffCtx = Depends(require(Perm.ORDERS_VIEW)),
                      db: AsyncSession = Depends(get_db)) -> Page[OrderOut]:
    statuses = list(PENDING_ORDER_STATUSES) if active else status
    items, total = await order_svc.list_orders(db, ctx.establishment_id, statuses=statuses, session_id=session_id,
                                               limit=limit, offset=offset)
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.post("/orders/{order_id}/status", response_model=OrderOut)
async def order_status(order_id: uuid.UUID, data: OrderStatusIn,
                       ctx: StaffCtx = Depends(require(Perm.ORDERS_UPDATE_STATUS)),
                       db: AsyncSession = Depends(get_db)) -> OrderOut:
    out = await order_svc.update_status(db, ctx, order_id, data.status, data.reason, data.expected_version)
    await db.commit()
    return out
