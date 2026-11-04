from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CustomerCtx
from app.core.errors import AppError
from app.domain.states import RequestStatus, RequestType
from app.models import DiningTable, Order, OrderItem, Product, ServiceRequest
from app.schemas import OrderIn, ServiceRequestOut
from app.services import tables as table_svc
from app.services.audit import audit
from app.services.requests import emit_request, load

MAX_ORDER_CENTS = 5_000_000  # R$ 50.000 por pedido — evita abuso


async def create_customer_order(db: AsyncSession, ctx: CustomerCtx, data: OrderIn) -> ServiceRequestOut:
    """Registra o pedido e avisa a equipe, que só precisa repassá-lo à cozinha."""
    if not ctx.establishment.orders_enabled:
        raise AppError(403, "orders_disabled", "Pedidos pelo celular não estão habilitados. Chame o atendente.")
    # Lock na mesa: serializa com o encerramento (impede pedido em sessão que está sendo encerrada).
    table = (await db.execute(select(DiningTable).where(DiningTable.id == ctx.table.id).with_for_update()
                              .execution_options(populate_existing=True))).scalar_one()
    if table.current_session_id != ctx.session.id:
        raise AppError(401, "session_ended", "Esta sessão da mesa foi encerrada.")

    product_ids = {i.product_id for i in data.items}
    products = {p.id: p for p in (await db.execute(select(Product).where(
        Product.id.in_(product_ids), Product.establishment_id == ctx.establishment.id))).scalars().all()}

    order = Order(establishment_id=ctx.establishment.id, session_id=ctx.session.id, table_id=table.id,
                  note=data.note, total_cents=0)
    order.items = []
    total = 0
    for item in data.items:
        p = products.get(item.product_id)
        if p is None or not p.active:
            raise AppError(422, "product_unavailable", "Um dos produtos não existe mais no cardápio.",
                           {"product_id": str(item.product_id)})
        if not p.available:
            raise AppError(422, "product_unavailable", f"{p.name} está indisponível no momento.",
                           {"product_id": str(p.id)})
        # Preço SEMPRE recalculado no servidor a partir do catálogo vigente.
        chosen = set(item.option_ids)
        if len(chosen) != len(item.option_ids):
            raise AppError(422, "invalid_options", "Adicional repetido.")
        opts_snapshot = []
        unit = p.price_cents
        valid_ids: set[uuid.UUID] = set()
        for g in p.option_groups:
            g_selected = [o for o in g.options if o.id in chosen]
            for o in g_selected:
                if not o.active:
                    raise AppError(422, "invalid_options", f"Adicional {o.name} indisponível.")
            if not (g.min_select <= len(g_selected) <= g.max_select):
                raise AppError(422, "invalid_options",
                               f"{p.name}: escolha entre {g.min_select} e {g.max_select} em “{g.name}”.")
            for o in g_selected:
                valid_ids.add(o.id)
                unit += o.price_cents
                opts_snapshot.append({"option_id": str(o.id), "group": g.name, "name": o.name,
                                      "price_cents": o.price_cents})
        if chosen - valid_ids:
            raise AppError(422, "invalid_options", "Adicional não pertence ao produto.")
        line = unit * item.quantity
        total += line
        order.items.append(OrderItem(product_id=p.id, product_name=p.name, unit_price_cents=unit,
                                     quantity=item.quantity, options=opts_snapshot, notes=item.notes,
                                     line_total_cents=line))
    if total > MAX_ORDER_CENTS:
        raise AppError(422, "order_too_large", "Pedido acima do limite. Chame o atendente.")
    order.total_cents = total
    db.add(order)
    await db.flush()
    req = ServiceRequest(establishment_id=ctx.establishment.id, session_id=ctx.session.id, table_id=table.id,
                         type=RequestType.NOVO_PEDIDO, status=RequestStatus.PENDENTE, order_id=order.id,
                         note=data.note)
    db.add(req)
    await db.flush()
    req = await load(db, req.id)
    audit(db, establishment_id=ctx.establishment.id, actor_kind="CLIENTE", action="order.create",
          target_type="order", target_id=order.id, details={"number": req.order.number if req.order else None,
                                                             "total_cents": total, "table": table.number})
    out = emit_request(db, req)
    await table_svc.emit_table(db, table)
    return out
