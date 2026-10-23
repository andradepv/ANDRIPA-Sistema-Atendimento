from __future__ import annotations

import io
import uuid

import segno
from fastapi import APIRouter, Depends, Header, Query, Request, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import StaffCtx, require
from app.core.permissions import Perm
from app.core.ratelimit import client_ip, hit
from app.db.session import get_db
from app.domain.states import SessionStatus
from app.models import DiningTable, TableSession, User
from app.schemas import (
    CloseSessionIn,
    OpenTableIn,
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
async def open_table(table_id: uuid.UUID, data: OpenTableIn, request: Request,
                     idempotency_key: str | None = Header(default=None),
                     ctx: StaffCtx = Depends(require(Perm.TABLES_OPEN)), db: AsyncSession = Depends(get_db)) -> Response:
    await hit(f"open:{ctx.user.id}", 30, 60)
    body = {"table_id": str(table_id), "label": data.label}  # o segredo não entra no hash armazenado
    return await run_idempotent(db, scope=f"open:{ctx.user.id}", key=idempotency_key, request_body=body,
                                status_code=201,
                                action=lambda: svc.open_table(db, ctx, table_id, data, client_ip(request)))


@router.post("/tables/{table_id}/request-close", response_model=TableOut)
async def request_close(table_id: uuid.UUID, ctx: StaffCtx = Depends(require(Perm.TABLES_REQUEST_CLOSE)),
                        db: AsyncSession = Depends(get_db)) -> TableOut:
    out = await svc.staff_request_close(db, ctx, table_id)
    await db.commit()
    return out


@router.post("/tables/{table_id}/cancel-close-request", response_model=TableOut)
async def cancel_close_request(table_id: uuid.UUID, ctx: StaffCtx = Depends(require(Perm.TABLES_CLOSE)),
                               db: AsyncSession = Depends(get_db)) -> TableOut:
    out = await svc.cancel_close_request(db, ctx, table_id)
    await db.commit()
    return out


@router.get("/table-sessions/{session_id}", response_model=SessionDetailOut)
async def session_detail(session_id: uuid.UUID, ctx: StaffCtx = Depends(require(Perm.TABLES_VIEW)),
                         db: AsyncSession = Depends(get_db)) -> SessionDetailOut:
    out = await svc.session_detail(db, ctx.establishment_id, session_id)
    if out.status != SessionStatus.OPEN.value and not ctx.can(Perm.HISTORY_VIEW):
        from app.core.errors import forbidden
        raise forbidden()
    return out


@router.post("/table-sessions/{session_id}/close", response_model=SessionDetailOut)
async def close_session(session_id: uuid.UUID, data: CloseSessionIn, request: Request,
                        idempotency_key: str | None = Header(default=None),
                        ctx: StaffCtx = Depends(require(Perm.TABLES_CLOSE)), db: AsyncSession = Depends(get_db)) -> Response:
    return await run_idempotent(db, scope=f"close:{session_id}", key=idempotency_key, request_body=data,
                                status_code=200,
                                action=lambda: svc.close_session(db, ctx, session_id, data, client_ip(request)))


@router.get("/table-sessions", response_model=Page[SessionHistoryOut])
async def session_history(status: SessionStatus = SessionStatus.CLOSED, table_number: int | None = None,
                          limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0, le=100_000),
                          ctx: StaffCtx = Depends(require(Perm.HISTORY_VIEW)),
                          db: AsyncSession = Depends(get_db)) -> Page[SessionHistoryOut]:
    q = select(TableSession).where(TableSession.establishment_id == ctx.establishment_id,
                                   TableSession.status == status)
    if table_number is not None:
        q = q.join(DiningTable, DiningTable.id == TableSession.table_id).where(DiningTable.number == table_number)
    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
    rows = (await db.execute(q.order_by(TableSession.opened_at.desc()).limit(limit).offset(offset))).unique().scalars().all()
    closer_ids = {s.closed_by_id for s in rows if s.closed_by_id}
    names = {u.id: u.name for u in (await db.execute(select(User).where(User.id.in_(closer_ids)))).scalars()} if closer_ids else {}
    items = [SessionHistoryOut(id=s.id, table_number=s.table.number, label=s.label, opened_at=s.opened_at,
                               closed_at=s.closed_at, opened_by_name=s.opened_by.name,
                               closed_by_name=names.get(s.closed_by_id) if s.closed_by_id else None,
                               total_cents=s.total_cents, payment_method=s.payment_method) for s in rows]
    return Page(items=items, total=int(total), limit=limit, offset=offset)
