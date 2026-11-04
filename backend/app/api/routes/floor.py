"""Provisionamento de mesas/etiquetas NFC e plantas do salão (rotas de administração)."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import StaffCtx, require
from app.core.permissions import Perm
from app.core.ratelimit import client_ip, hit
from app.db.session import get_db
from app.schemas import (
    LayoutCreateIn,
    LayoutItemsIn,
    LayoutOut,
    LayoutRenameIn,
    ProvisionIn,
    ProvisionOut,
    TagFailedIn,
    TagLockAuthIn,
    TagOut,
    TagStartIn,
    TagWrittenIn,
)
from app.services import layouts as layout_svc
from app.services import tags as tag_svc

router = APIRouter(tags=["floor"])


# ---------- etiquetas NFC ----------
@router.post("/admin/tables/provision", response_model=ProvisionOut, status_code=201)
async def provision(data: ProvisionIn, request: Request, ctx: StaffCtx = Depends(require(Perm.TABLES_PROVISION)),
                    db: AsyncSession = Depends(get_db)) -> ProvisionOut:
    await hit(f"confirm:{ctx.user.id}", 30, 60)
    out = await tag_svc.provision_table(db, ctx, data, client_ip(request))
    await db.commit()
    return out


@router.post("/admin/tables/{table_id}/tag", response_model=TagOut, status_code=201)
async def start_tag(table_id: uuid.UUID, data: TagStartIn, request: Request,
                    ctx: StaffCtx = Depends(require(Perm.TABLES_PROVISION)),
                    db: AsyncSession = Depends(get_db)) -> TagOut:
    await hit(f"confirm:{ctx.user.id}", 30, 60)
    out = await tag_svc.start_tag(db, ctx, table_id, data, client_ip(request))
    await db.commit()
    return out


@router.get("/admin/tags", response_model=list[TagOut])
async def list_tags(ctx: StaffCtx = Depends(require(Perm.TABLES_PROVISION)),
                    db: AsyncSession = Depends(get_db)) -> list[TagOut]:
    return await tag_svc.list_tags(db, ctx.establishment_id)


@router.post("/admin/tags/{tag_id}/writing", response_model=TagOut)
async def tag_writing(tag_id: uuid.UUID, ctx: StaffCtx = Depends(require(Perm.TABLES_PROVISION)),
                      db: AsyncSession = Depends(get_db)) -> TagOut:
    out = await tag_svc.mark_writing(db, ctx, tag_id)
    await db.commit()
    return out


@router.post("/admin/tags/{tag_id}/written", response_model=TagOut)
async def tag_written(tag_id: uuid.UUID, data: TagWrittenIn, request: Request,
                      ctx: StaffCtx = Depends(require(Perm.TABLES_PROVISION)),
                      db: AsyncSession = Depends(get_db)) -> TagOut:
    out = await tag_svc.mark_written(db, ctx, tag_id, data, client_ip(request))
    await db.commit()
    return out


@router.post("/admin/tags/{tag_id}/failed", response_model=TagOut)
async def tag_failed(tag_id: uuid.UUID, data: TagFailedIn, ctx: StaffCtx = Depends(require(Perm.TABLES_PROVISION)),
                     db: AsyncSession = Depends(get_db)) -> TagOut:
    out = await tag_svc.mark_failed(db, ctx, tag_id, data.reason)
    await db.commit()
    return out


@router.post("/admin/tags/{tag_id}/authorize-lock", response_model=TagOut)
async def tag_authorize_lock(tag_id: uuid.UUID, data: TagLockAuthIn, request: Request,
                             ctx: StaffCtx = Depends(require(Perm.TABLES_PROVISION)),
                             db: AsyncSession = Depends(get_db)) -> TagOut:
    await hit(f"confirm:{ctx.user.id}", 30, 60)
    out = await tag_svc.authorize_lock(db, ctx, tag_id, data.confirm_secret, client_ip(request))
    await db.commit()
    return out


@router.post("/admin/tags/{tag_id}/locked", response_model=TagOut)
async def tag_locked(tag_id: uuid.UUID, request: Request, ctx: StaffCtx = Depends(require(Perm.TABLES_PROVISION)),
                     db: AsyncSession = Depends(get_db)) -> TagOut:
    out = await tag_svc.mark_locked(db, ctx, tag_id, client_ip(request))
    await db.commit()
    return out


# ---------- plantas do salão ----------
@router.get("/layouts/active", response_model=LayoutOut)
async def active_layout(ctx: StaffCtx = Depends(require(Perm.TABLES_VIEW)),
                        db: AsyncSession = Depends(get_db)) -> LayoutOut:
    layout = await layout_svc.get_active(db, ctx.establishment_id)
    out = layout_svc.layout_out(layout)
    await db.commit()
    return out


@router.get("/admin/layouts", response_model=list[LayoutOut])
async def list_layouts(ctx: StaffCtx = Depends(require(Perm.LAYOUTS_MANAGE)),
                       db: AsyncSession = Depends(get_db)) -> list[LayoutOut]:
    out = await layout_svc.list_layouts(db, ctx.establishment_id)
    await db.commit()
    return out


@router.post("/admin/layouts", response_model=LayoutOut, status_code=201)
async def create_layout(data: LayoutCreateIn, ctx: StaffCtx = Depends(require(Perm.LAYOUTS_MANAGE)),
                        db: AsyncSession = Depends(get_db)) -> LayoutOut:
    out = await layout_svc.create_layout(db, ctx, data)
    await db.commit()
    return out


@router.patch("/admin/layouts/{layout_id}", response_model=LayoutOut)
async def rename_layout(layout_id: uuid.UUID, data: LayoutRenameIn,
                        ctx: StaffCtx = Depends(require(Perm.LAYOUTS_MANAGE)),
                        db: AsyncSession = Depends(get_db)) -> LayoutOut:
    out = await layout_svc.rename_layout(db, ctx, layout_id, data.name)
    await db.commit()
    return out


@router.put("/admin/layouts/{layout_id}/items", response_model=LayoutOut)
async def set_items(layout_id: uuid.UUID, data: LayoutItemsIn, ctx: StaffCtx = Depends(require(Perm.LAYOUTS_MANAGE)),
                    db: AsyncSession = Depends(get_db)) -> LayoutOut:
    out = await layout_svc.set_items(db, ctx, layout_id, data)
    await db.commit()
    return out


@router.post("/admin/layouts/{layout_id}/activate", response_model=LayoutOut)
async def activate_layout(layout_id: uuid.UUID, ctx: StaffCtx = Depends(require(Perm.LAYOUTS_MANAGE)),
                          db: AsyncSession = Depends(get_db)) -> LayoutOut:
    out = await layout_svc.activate(db, ctx, layout_id)
    await db.commit()
    return out


@router.delete("/admin/layouts/{layout_id}", status_code=204)
async def delete_layout(layout_id: uuid.UUID, ctx: StaffCtx = Depends(require(Perm.LAYOUTS_MANAGE)),
                        db: AsyncSession = Depends(get_db)) -> Response:
    await layout_svc.delete_layout(db, ctx, layout_id)
    await db.commit()
    return Response(status_code=204)
