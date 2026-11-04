from __future__ import annotations

import io
import uuid

import segno
from fastapi import APIRouter, Depends, Header, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import StaffCtx, require
from app.core.errors import forbidden
from app.core.permissions import Perm
from app.core.ratelimit import client_ip, hit
from app.db.session import get_db
from app.domain.states import SessionStatus
from app.models import DiningTable
from app.schemas import (
    Page,
    SessionDetailOut,
    SessionHistoryOut,
    TableCreate,
    TableOut,
    TablePatch,
)
from app.services import tables as svc
from app.services.idempotency import run_idempotent
from app.services.serializers import public_url, tables_out

router = APIRouter(tags=["tables"])


@router.get("/tables", response_model=list[TableOut])
async def list_tables(include_inactive: bool = False, ctx: StaffCtx = Depends(require(Perm.TABLES_VIEW)),
                      db: AsyncSession = Depends(get_db)) -> list[TableOut]:
    q = select(DiningTable).where(DiningTable.establishment_id == ctx.establishment_id)
    if not include_inactive:
        q = q.where(DiningTable.active.is_(True))
    rows = (await db.execute(q.order_by(DiningTable.number))).scalars().all()
    return await tables_out(db, list(rows))


@router.post("/tables", response_model=TableOut, status_code=201)
async def create_table(data: TableCreate, ctx: StaffCtx = Depends(require(Perm.TABLES_MANAGE)),
                       db: AsyncSession = Depends(get_db)) -> TableOut:
    out = await svc.create_table(db, ctx, data)
    await db.commit()
    return out


@router.patch("/tables/{table_id}", response_model=TableOut)
async def patch_table(table_id: uuid.UUID, data: TablePatch, ctx: StaffCtx = Depends(require(Perm.TABLES_MANAGE)),
                      db: AsyncSession = Depends(get_db)) -> TableOut:
    out = await svc.patch_table(db, ctx, table_id, data)
    await db.commit()
    return out


@router.post("/tables/{table_id}/rotate-code", response_model=TableOut)
async def rotate_code(table_id: uuid.UUID, ctx: StaffCtx = Depends(require(Perm.TABLES_MANAGE)),
                      db: AsyncSession = Depends(get_db)) -> TableOut:
    out = await svc.rotate_code(db, ctx, table_id)
    await db.commit()
    return out


@router.get("/tables/{table_id}/qr.svg", response_class=Response)
async def table_qr(table_id: uuid.UUID, ctx: StaffCtx = Depends(require(Perm.TABLES_MANAGE)),
                   db: AsyncSession = Depends(get_db)) -> Response:
    t = await svc.get_table(db, ctx.establishment_id, table_id)
    qr = segno.make(public_url(t), error="m")
    buf = io.BytesIO()
    qr.save(buf, kind="svg", scale=8, border=2, dark="#000", light="#fff", xmldecl=True, svgns=True)
    return Response(content=buf.getvalue(), media_type="image/svg+xml",
                    headers={"Content-Disposition": f'inline; filename="mesa-{t.number}.svg"',
                             "Cache-Control": "no-store"})


@router.post("/tables/{table_id}/open", response_model=TableOut, status_code=201)
async def open_table(table_id: uuid.UUID, request: Request, idempotency_key: str | None = Header(default=None),
                     ctx: StaffCtx = Depends(require(Perm.TABLES_OPEN)), db: AsyncSession = Depends(get_db)) -> Response:
    await hit(f"open:{ctx.user.id}", 30, 60)
    return await run_idempotent(db, scope=f"open:{ctx.user.id}", key=idempotency_key,
                                request_body={"table_id": str(table_id)}, status_code=201,
                                action=lambda: svc.staff_open(db, ctx, table_id, client_ip(request)))


@router.post("/tables/{table_id}/close", response_model=TableOut)
async def close_table(table_id: uuid.UUID, request: Request, idempotency_key: str | None = Header(default=None),
                      ctx: StaffCtx = Depends(require(Perm.TABLES_CLOSE)), db: AsyncSession = Depends(get_db)) -> Response:
    """Conta finalizada: encerra o atendimento e libera a mesa para os próximos clientes."""
    return await run_idempotent(db, scope=f"close:{table_id}", key=idempotency_key,
                                request_body={"table_id": str(table_id)}, status_code=200,
                                action=lambda: svc.close_table(db, ctx, table_id, client_ip(request)))


@router.get("/table-sessions/{session_id}", response_model=SessionDetailOut)
async def session_detail(session_id: uuid.UUID, ctx: StaffCtx = Depends(require(Perm.TABLES_VIEW)),
                         db: AsyncSession = Depends(get_db)) -> SessionDetailOut:
    out = await svc.session_detail(db, ctx.establishment_id, session_id)
    if out.status != SessionStatus.OPEN.value and not ctx.can(Perm.HISTORY_VIEW):
        raise forbidden()
    return out


@router.get("/table-sessions", response_model=Page[SessionHistoryOut])
async def session_history(table_id: uuid.UUID | None = None, limit: int = Query(20, ge=1, le=200),
                          offset: int = Query(0, ge=0, le=100_000),
                          ctx: StaffCtx = Depends(require(Perm.HISTORY_VIEW)),
                          db: AsyncSession = Depends(get_db)) -> Page[SessionHistoryOut]:
    items, total = await svc.history(db, ctx.establishment_id, table_id=table_id, limit=limit, offset=offset)
    return Page(items=items, total=total, limit=limit, offset=offset)
