"""Solicitações das mesas (chamados, pedidos e conta) — lado da equipe."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import StaffCtx, require
from app.core.permissions import Perm
from app.core.ratelimit import client_ip
from app.db.session import get_db
from app.schemas import Page, ServiceRequestOut
from app.services import requests as req_svc

router = APIRouter(tags=["operations"])


@router.get("/service-requests", response_model=Page[ServiceRequestOut])
async def list_pending(session_id: uuid.UUID | None = None, limit: int = Query(200, ge=1, le=500),
                       offset: int = Query(0, ge=0), ctx: StaffCtx = Depends(require(Perm.TABLES_VIEW)),
                       db: AsyncSession = Depends(get_db)) -> Page[ServiceRequestOut]:
    """Solicitações aguardando resposta, das mais antigas para as mais novas."""
    items, total = await req_svc.list_pending(db, ctx.establishment_id, limit=limit, offset=offset,
                                              session_id=session_id)
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.post("/service-requests/{request_id}/complete", response_model=ServiceRequestOut,
             summary="Atendido / repassado à cozinha / conta finalizada")
async def complete(request_id: uuid.UUID, request: Request, ctx: StaffCtx = Depends(require(Perm.REQUESTS_HANDLE)),
                   db: AsyncSession = Depends(get_db)) -> ServiceRequestOut:
    out = await req_svc.complete(db, ctx, request_id, client_ip(request))
    await db.commit()
    return out
