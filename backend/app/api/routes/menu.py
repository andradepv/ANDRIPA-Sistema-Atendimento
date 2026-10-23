from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import StaffCtx, get_staff, require
from app.core.permissions import Perm
from app.db.session import get_db
from app.schemas import CategoryIn, CategoryOut, CategoryPatch, ProductIn, ProductOut, ProductPatch
from app.services import menu as svc

router = APIRouter(prefix="/menu", tags=["menu"])


@router.get("/categories", response_model=list[CategoryOut])
async def categories(ctx: StaffCtx = Depends(get_staff), db: AsyncSession = Depends(get_db)) -> list[CategoryOut]:
    return await svc.list_categories(db, ctx.establishment_id)


@router.post("/categories", response_model=CategoryOut, status_code=201)
async def create_category(data: CategoryIn, ctx: StaffCtx = Depends(require(Perm.MENU_MANAGE)),
                          db: AsyncSession = Depends(get_db)) -> CategoryOut:
    out = await svc.create_category(db, ctx, data)
    await db.commit()
    return out


@router.patch("/categories/{category_id}", response_model=CategoryOut)
async def patch_category(category_id: uuid.UUID, data: CategoryPatch,
                         ctx: StaffCtx = Depends(require(Perm.MENU_MANAGE)),
                         db: AsyncSession = Depends(get_db)) -> CategoryOut:
    out = await svc.patch_category(db, ctx, category_id, data)
    await db.commit()
    return out


@router.get("/products", response_model=list[ProductOut])
async def products(ctx: StaffCtx = Depends(get_staff), db: AsyncSession = Depends(get_db)) -> list[ProductOut]:
    return await svc.list_products(db, ctx.establishment_id)


@router.post("/products", response_model=ProductOut, status_code=201)
async def create_product(data: ProductIn, ctx: StaffCtx = Depends(require(Perm.MENU_MANAGE)),
                         db: AsyncSession = Depends(get_db)) -> ProductOut:
    out = await svc.create_product(db, ctx, data)
    await db.commit()
    return out


@router.patch("/products/{product_id}", response_model=ProductOut)
async def patch_product(product_id: uuid.UUID, data: ProductPatch, ctx: StaffCtx = Depends(require(Perm.MENU_MANAGE)),
                        db: AsyncSession = Depends(get_db)) -> ProductOut:
    out = await svc.patch_product(db, ctx, product_id, data)
    await db.commit()
    return out
