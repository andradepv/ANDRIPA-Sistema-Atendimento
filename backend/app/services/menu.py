from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import StaffCtx
from app.core.errors import AppError, conflict, not_found
from app.models import Category, OptionGroup, Product, ProductOption
from app.schemas import (
    CategoryIn,
    CategoryOut,
    CategoryPatch,
    MenuCategoryOut,
    OptionGroupIn,
    OptionGroupOut,
    OptionOut,
    ProductIn,
    ProductOut,
    ProductPatch,
)
from app.services.audit import audit
from app.services.events import CUSTOMERS, STAFF, emit


def product_out(p: Product, *, only_active_options: bool = False) -> ProductOut:
    groups = []
    for g in p.option_groups:
        opts = [o for o in g.options if o.active or not only_active_options]
        groups.append(OptionGroupOut(id=g.id, name=g.name, min_select=g.min_select, max_select=g.max_select,
                                     options=[OptionOut.model_validate(o) for o in opts]))
    return ProductOut(id=p.id, category_id=p.category_id, name=p.name, description=p.description,
                      price_cents=p.price_cents, image_url=p.image_url, available=p.available, active=p.active,
                      position=p.position, option_groups=groups)


def _menu_changed(db: AsyncSession, est_id: uuid.UUID) -> None:
    emit(db, est_id, "menu.updated", {}, audience=(STAFF, CUSTOMERS))


async def list_categories(db: AsyncSession, est_id: uuid.UUID) -> list[CategoryOut]:
    rows = (await db.execute(select(Category).where(Category.establishment_id == est_id)
                             .order_by(Category.position, Category.name))).scalars().all()
    return [CategoryOut.model_validate(c) for c in rows]


async def create_category(db: AsyncSession, ctx: StaffCtx, data: CategoryIn) -> CategoryOut:
    c = Category(establishment_id=ctx.establishment_id, **data.model_dump())
    db.add(c)
    try:
        await db.flush()
    except IntegrityError as e:
        raise conflict("category_exists", "Já existe uma categoria com esse nome.") from e
    audit(db, establishment_id=ctx.establishment_id, actor_id=ctx.user.id, action="category.create",
          target_type="category", target_id=c.id, details={"name": c.name})
    _menu_changed(db, ctx.establishment_id)
    return CategoryOut.model_validate(c)


async def patch_category(db: AsyncSession, ctx: StaffCtx, cat_id: uuid.UUID, data: CategoryPatch) -> CategoryOut:
    c = (await db.execute(select(Category).where(Category.id == cat_id,
                                                 Category.establishment_id == ctx.establishment_id))).scalar_one_or_none()
    if c is None:
        raise not_found("Categoria")
    changes = data.model_dump(exclude_unset=True)
    for k, v in changes.items():
        setattr(c, k, v)
    try:
        await db.flush()
    except IntegrityError as e:
        raise conflict("category_exists", "Já existe uma categoria com esse nome.") from e
    await db.refresh(c)
    audit(db, establishment_id=ctx.establishment_id, actor_id=ctx.user.id, action="category.update",
          target_type="category", target_id=c.id, details=changes)
    _menu_changed(db, ctx.establishment_id)
    return CategoryOut.model_validate(c)


async def _check_category(db: AsyncSession, est_id: uuid.UUID, cat_id: uuid.UUID) -> None:
    c = (await db.execute(select(Category.id).where(Category.id == cat_id,
                                                    Category.establishment_id == est_id))).scalar_one_or_none()
    if c is None:
        raise AppError(422, "invalid_category", "Categoria inexistente.")


def _apply_groups(p: Product, groups: list[OptionGroupIn]) -> None:
    """Sincroniza grupos/opções. Opções removidas são inativadas (preserva histórico)."""
    existing = {g.id: g for g in p.option_groups}
    keep: list[OptionGroup] = []
    for gi, gdata in enumerate(groups):
        g = existing.get(gdata.id) if gdata.id else None
        if gdata.id and g is None:
            raise AppError(422, "invalid_option_group", "Grupo de adicionais inexistente.")
        if g is None:
            g = OptionGroup(name=gdata.name, min_select=gdata.min_select, max_select=gdata.max_select, position=gi)
            g.options = []
        else:
            g.name, g.min_select, g.max_select, g.position = gdata.name, gdata.min_select, gdata.max_select, gi
        ex_opts = {o.id: o for o in g.options}
        seen: set[uuid.UUID] = set()
        for oi, odata in enumerate(gdata.options):
            o = ex_opts.get(odata.id) if odata.id else None
            if odata.id and o is None:
                raise AppError(422, "invalid_option", "Adicional inexistente.")
            if o is None:
                g.options.append(ProductOption(name=odata.name, price_cents=odata.price_cents,
                                               active=odata.active, position=oi))
            else:
                o.name, o.price_cents, o.active, o.position = odata.name, odata.price_cents, odata.active, oi
                seen.add(o.id)
        for oid, o in ex_opts.items():
            if oid not in seen:
                o.active = False
        keep.append(g)
    # Grupos removidos: mantidos, mas com todas as opções inativas e fora da exibição.
    for g in existing.values():
        if g not in keep:
            for o in g.options:
                o.active = False
            g.position = 1000 + g.position
            keep.append(g)
    p.option_groups = keep


async def get_product(db: AsyncSession, est_id: uuid.UUID, product_id: uuid.UUID) -> Product:
    p = (await db.execute(select(Product).where(Product.id == product_id, Product.establishment_id == est_id)
                          .execution_options(populate_existing=True))).scalar_one_or_none()
    if p is None:
        raise not_found("Produto")
    return p


async def create_product(db: AsyncSession, ctx: StaffCtx, data: ProductIn) -> ProductOut:
    await _check_category(db, ctx.establishment_id, data.category_id)
    p = Product(establishment_id=ctx.establishment_id,
                **data.model_dump(exclude={"option_groups"}))
    p.option_groups = []
    _apply_groups(p, data.option_groups)
    db.add(p)
    await db.flush()
    audit(db, establishment_id=ctx.establishment_id, actor_id=ctx.user.id, action="product.create",
          target_type="product", target_id=p.id, details={"name": p.name, "price_cents": p.price_cents})
    _menu_changed(db, ctx.establishment_id)
    return product_out(await get_product(db, ctx.establishment_id, p.id))


async def patch_product(db: AsyncSession, ctx: StaffCtx, product_id: uuid.UUID, data: ProductPatch) -> ProductOut:
    p = await get_product(db, ctx.establishment_id, product_id)
    changes = data.model_dump(exclude_unset=True, exclude={"option_groups"})
    if "category_id" in changes:
        await _check_category(db, ctx.establishment_id, changes["category_id"])
    for k, v in changes.items():
        setattr(p, k, v)
    if data.option_groups is not None:
        _apply_groups(p, data.option_groups)
    await db.flush()
    audit(db, establishment_id=ctx.establishment_id, actor_id=ctx.user.id, action="product.update",
          target_type="product", target_id=p.id, details={k: str(v) for k, v in changes.items()})
    _menu_changed(db, ctx.establishment_id)
    return product_out(await get_product(db, ctx.establishment_id, p.id))


async def list_products(db: AsyncSession, est_id: uuid.UUID) -> list[ProductOut]:
    rows = (await db.execute(select(Product).where(Product.establishment_id == est_id)
                             .order_by(Product.position, Product.name))).scalars().all()
    return [product_out(p) for p in rows]


async def public_menu(db: AsyncSession, est_id: uuid.UUID) -> list[MenuCategoryOut]:
    cats = (await db.execute(select(Category).where(Category.establishment_id == est_id, Category.active.is_(True))
                             .order_by(Category.position, Category.name))).scalars().all()
    prods = (await db.execute(select(Product).where(Product.establishment_id == est_id, Product.active.is_(True))
                              .order_by(Product.position, Product.name))).scalars().all()
    by_cat: dict[uuid.UUID, list[ProductOut]] = {}
    for p in prods:
        po = product_out(p, only_active_options=True)
        po.option_groups = [g for g in po.option_groups if g.options or g.min_select > 0]
        by_cat.setdefault(p.category_id, []).append(po)
    return [MenuCategoryOut(id=c.id, name=c.name, products=by_cat.get(c.id, [])) for c in cats if by_cat.get(c.id)]
