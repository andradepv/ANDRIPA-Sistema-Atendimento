"""Plantas (templates) do salão. Só o administrador altera; todos os painéis acompanham a planta ativa.

Cada planta guarda a posição (célula x, y de uma grade) de cada mesa. Mesas sem posição na planta ativa
aparecem numa bandeja "sem posição", então nenhuma mesa some quando o salão é rearranjado.
"""
from __future__ import annotations

import uuid

from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import StaffCtx
from app.core.errors import AppError, conflict, not_found
from app.models import DiningTable, FloorLayout, FloorLayoutItem
from app.schemas import GRID_COLS, GRID_ROWS, LayoutCreateIn, LayoutItem, LayoutItemsIn, LayoutOut
from app.services.audit import audit
from app.services.events import STAFF, emit

DEFAULT_NAME = "Padrão"
DEFAULT_COLS = 12  # a auto-posição prefere as 12 primeiras colunas (grade compacta)


def layout_out(layout: FloorLayout) -> LayoutOut:
    return LayoutOut(
        id=layout.id, name=layout.name, is_active=layout.is_active, version=layout.version,
        items=[LayoutItem(table_id=i.table_id, x=i.x, y=i.y) for i in layout.items],
        updated_at=layout.updated_at,
    )


def _emit(db: AsyncSession, layout: FloorLayout) -> None:
    emit(db, layout.establishment_id, "layout.updated", {"layout": layout_out(layout).model_dump(mode="json")},
         audience=(STAFF,))


async def _load(db: AsyncSession, layout_id: uuid.UUID, *, lock: bool = False,
                est_id: uuid.UUID | None = None) -> FloorLayout:
    q = select(FloorLayout).where(FloorLayout.id == layout_id)
    if est_id is not None:
        q = q.where(FloorLayout.establishment_id == est_id)
    q = q.execution_options(populate_existing=True)
    if lock:
        q = q.with_for_update(of=FloorLayout)
    row = (await db.execute(q)).unique().scalar_one_or_none()
    if row is None:
        raise not_found("Planta")
    return row


def _free_cells(used: set[tuple[int, int]], *, compact: bool) -> list[tuple[int, int]]:
    cols = DEFAULT_COLS if compact else GRID_COLS
    return [(x, y) for y in range(GRID_ROWS) for x in range(cols) if (x, y) not in used]


async def get_active(db: AsyncSession, est_id: uuid.UUID) -> FloorLayout:
    """Planta ativa do estabelecimento; cria a "Padrão" (com as mesas ativas) se ainda não existir."""
    q = (select(FloorLayout).where(FloorLayout.establishment_id == est_id, FloorLayout.is_active.is_(True))
         .execution_options(populate_existing=True))
    active = (await db.execute(q)).unique().scalar_one_or_none()
    if active is not None:
        return active
    # Serializa a criação inicial: vários painéis podem pedir a planta ao mesmo tempo.
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": f"layout-init|{est_id}"})
    active = (await db.execute(q)).unique().scalar_one_or_none()
    if active is not None:
        return active
    existing_default = (await db.execute(select(FloorLayout).where(
        FloorLayout.establishment_id == est_id, FloorLayout.name == DEFAULT_NAME)
        .execution_options(populate_existing=True))).unique().scalar_one_or_none()
    if existing_default is not None:
        existing_default.is_active = True
        existing_default.version += 1
        await db.flush()
        return existing_default
    tables = (await db.execute(select(DiningTable).where(
        DiningTable.establishment_id == est_id, DiningTable.active.is_(True)).order_by(DiningTable.number))
    ).scalars().all()
    cells = _free_cells(set(), compact=True) + [c for c in _free_cells(set(), compact=False) if c[0] >= DEFAULT_COLS]
    layout = FloorLayout(establishment_id=est_id, name=DEFAULT_NAME, is_active=True,
                         items=[FloorLayoutItem(table_id=t.id, x=x, y=y) for t, (x, y) in zip(tables, cells, strict=False)])
    db.add(layout)
    await db.flush()
    return await _load(db, layout.id)


async def auto_place(db: AsyncSession, est_id: uuid.UUID, table_id: uuid.UUID) -> None:
    """Coloca uma mesa nova na primeira célula livre da planta ativa."""
    layout = await get_active(db, est_id)
    layout = await _load(db, layout.id, lock=True)
    if any(i.table_id == table_id for i in layout.items):
        return  # a planta inicial acabou de ser criada já contendo esta mesa
    used = {(i.x, i.y) for i in layout.items}
    cells = _free_cells(used, compact=True) or _free_cells(used, compact=False)
    if not cells:
        return  # grade cheia: a mesa aparece na bandeja "sem posição"
    x, y = cells[0]
    db.add(FloorLayoutItem(layout_id=layout.id, table_id=table_id, x=x, y=y))
    layout.version += 1
    await db.flush()
    _emit(db, await _load(db, layout.id))


async def list_layouts(db: AsyncSession, est_id: uuid.UUID) -> list[LayoutOut]:
    await get_active(db, est_id)
    rows = (await db.execute(select(FloorLayout).where(FloorLayout.establishment_id == est_id)
                             .order_by(FloorLayout.name).execution_options(populate_existing=True))).unique().scalars().all()
    return [layout_out(r) for r in rows]


async def create_layout(db: AsyncSession, ctx: StaffCtx, data: LayoutCreateIn) -> LayoutOut:
    items: list[FloorLayoutItem] = []
    if data.copy_from is not None:
        src = await _load(db, data.copy_from, est_id=ctx.establishment_id)
        items = [FloorLayoutItem(table_id=i.table_id, x=i.x, y=i.y) for i in src.items]
    layout = FloorLayout(establishment_id=ctx.establishment_id, name=data.name, is_active=False, items=items)
    db.add(layout)
    try:
        await db.flush()
    except IntegrityError as e:
        raise conflict("layout_name_taken", f"Já existe uma planta chamada “{data.name}”.") from e
    layout = await _load(db, layout.id)
    audit(db, establishment_id=ctx.establishment_id, actor_id=ctx.user.id, action="layout.create",
          target_type="layout", target_id=layout.id, details={"name": data.name,
                                                               "copy_from": str(data.copy_from) if data.copy_from else None})
    return layout_out(layout)


async def rename_layout(db: AsyncSession, ctx: StaffCtx, layout_id: uuid.UUID, name: str) -> LayoutOut:
    layout = await _load(db, layout_id, lock=True, est_id=ctx.establishment_id)
    layout.name = name
    layout.version += 1
    try:
        await db.flush()
    except IntegrityError as e:
        raise conflict("layout_name_taken", f"Já existe uma planta chamada “{name}”.") from e
    layout = await _load(db, layout.id)
    audit(db, establishment_id=ctx.establishment_id, actor_id=ctx.user.id, action="layout.rename",
          target_type="layout", target_id=layout.id, details={"name": name})
    if layout.is_active:
        _emit(db, layout)
    return layout_out(layout)


async def set_items(db: AsyncSession, ctx: StaffCtx, layout_id: uuid.UUID, data: LayoutItemsIn) -> LayoutOut:
    layout = await _load(db, layout_id, lock=True, est_id=ctx.establishment_id)
    if layout.version != data.version:
        raise conflict("stale_version", "A planta foi alterada por outra pessoa. Recarregue e refaça a mudança.",
                       current_version=layout.version)
    ids = [i.table_id for i in data.items]
    if len(set(ids)) != len(ids):
        raise AppError(422, "duplicate_table", "Uma mesa não pode aparecer duas vezes na planta.")
    cells = [(i.x, i.y) for i in data.items]
    if len(set(cells)) != len(cells):
        raise AppError(422, "cell_taken", "Duas mesas não podem ocupar a mesma posição.")
    if ids:
        found = set((await db.execute(select(DiningTable.id).where(
            DiningTable.establishment_id == ctx.establishment_id, DiningTable.id.in_(ids)))).scalars())
        if found != set(ids):
            raise AppError(422, "unknown_table", "A planta referencia uma mesa que não existe.")
    await db.execute(delete(FloorLayoutItem).where(FloorLayoutItem.layout_id == layout.id))
    await db.flush()
    db.add_all([FloorLayoutItem(layout_id=layout.id, table_id=i.table_id, x=i.x, y=i.y) for i in data.items])
    layout.version += 1
    await db.flush()
    layout = await _load(db, layout.id)
    audit(db, establishment_id=ctx.establishment_id, actor_id=ctx.user.id, action="layout.update",
          target_type="layout", target_id=layout.id, details={"name": layout.name, "tables": len(ids)})
    if layout.is_active:
        _emit(db, layout)
    return layout_out(layout)


async def activate(db: AsyncSession, ctx: StaffCtx, layout_id: uuid.UUID) -> LayoutOut:
    # Trava todas as plantas do estabelecimento em ordem fixa (evita deadlock entre ativações simultâneas).
    await db.execute(select(FloorLayout.id).where(FloorLayout.establishment_id == ctx.establishment_id)
                     .order_by(FloorLayout.id).with_for_update())
    layout = await _load(db, layout_id, lock=True, est_id=ctx.establishment_id)
    if not layout.is_active:
        others = (await db.execute(select(FloorLayout).where(
            FloorLayout.establishment_id == ctx.establishment_id, FloorLayout.is_active.is_(True))
            .execution_options(populate_existing=True))).unique().scalars().all()
        for o in others:
            o.is_active = False
            o.version += 1
        await db.flush()
        layout.is_active = True
        layout.version += 1
        await db.flush()
        layout = await _load(db, layout.id)
        audit(db, establishment_id=ctx.establishment_id, actor_id=ctx.user.id, action="layout.activate",
              target_type="layout", target_id=layout.id, details={"name": layout.name})
        _emit(db, layout)
    return layout_out(layout)


async def delete_layout(db: AsyncSession, ctx: StaffCtx, layout_id: uuid.UUID) -> None:
    layout = await _load(db, layout_id, lock=True, est_id=ctx.establishment_id)
    if layout.is_active:
        raise conflict("layout_active", "Ative outra planta antes de excluir esta.")
    audit(db, establishment_id=ctx.establishment_id, actor_id=ctx.user.id, action="layout.delete",
          target_type="layout", target_id=layout.id, details={"name": layout.name})
    await db.delete(layout)
    await db.flush()
