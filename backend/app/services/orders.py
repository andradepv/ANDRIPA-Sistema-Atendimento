from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CustomerCtx, StaffCtx
from app.core.errors import AppError, not_found
from app.core.permissions import Perm
from app.domain.states import ORDER_TRANSITIONS, OrderStatus, RequestStatus, RequestType, ensure_transition
from app.models import DiningTable, Order, OrderItem, OrderStatusHistory, Product, ServiceRequest
from app.schemas import OrderIn, OrderOut
from app.services import tables as table_svc
from app.services.audit import audit
from app.services.events import SESSION, STAFF, emit
from app.services.serializers import order_out, request_out

MAX_ORDER_CENTS = 5_000_000  # R$ 50.000 por pedido — evita abuso


async def _load(db: AsyncSession, order_id: uuid.UUID) -> Order:
    return (await db.execute(select(Order).where(Order.id == order_id)
                             .execution_options(populate_existing=True))).unique().scalar_one()


def _emit(db: AsyncSession, o: Order) -> OrderOut:
    out = order_out(o)
    emit(db, o.establishment_id, "order.updated", {"order": out.model_dump(mode="json")},
         session_id=o.session_id, audience=(STAFF, SESSION))
    return out


async def create_customer_order(db: AsyncSession, ctx: CustomerCtx, data: OrderIn) -> OrderOut:
    if not ctx.establishment.orders_enabled:
        raise AppError(403, "orders_disabled", "Pedidos pelo celular não estão habilitados. Chame o atendente.")
    # Lock na mesa: serializa com o encerramento (impede pedido em sessão que está sendo encerrada).
    table = (await db.execute(select(DiningTable).where(DiningTable.id == ctx.table.id).with_for_update().execution_options(populate_existing=True))).scalar_one()
    if table.current_session_id != ctx.session.id:
        raise AppError(401, "session_ended", "Esta sessão da mesa foi encerrada.")

    product_ids = {i.product_id for i in data.items}
    products = {p.id: p for p in (await db.execute(select(Product).where(
        Product.id.in_(product_ids), Product.establishment_id == ctx.establishment.id))).scalars().all()}

    order = Order(establishment_id=ctx.establishment.id, session_id=ctx.session.id, table_id=table.id,
                  status=OrderStatus.RECEBIDO, origin="CLIENTE", note=data.note, total_cents=0)
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
    db.add(OrderStatusHistory(order_id=order.id, from_status=None, to_status=OrderStatus.RECEBIDO.value))
    req = ServiceRequest(establishment_id=ctx.establishment.id, session_id=ctx.session.id, table_id=table.id,
                         type=RequestType.NOVO_PEDIDO, status=RequestStatus.PENDENTE, order_id=order.id,
                         origin="CLIENTE")
    db.add(req)
    await db.flush()
    order = await _load(db, order.id)
    req = (await db.execute(select(ServiceRequest).where(ServiceRequest.id == req.id))).unique().scalar_one()
    audit(db, establishment_id=ctx.establishment.id, actor_kind="CLIENTE", action="order.create",
          target_type="order", target_id=order.id, details={"number": order.number, "total_cents": total})
    out = _emit(db, order)
    emit(db, ctx.establishment.id, "request.updated", {"request": request_out(req).model_dump(mode="json")},
         session_id=ctx.session.id, audience=(STAFF, SESSION))
    await table_svc.emit_table(db, table)
    return out


async def list_orders(db: AsyncSession, est_id: uuid.UUID, *, statuses: list[OrderStatus] | None,
                      session_id: uuid.UUID | None, limit: int, offset: int) -> tuple[list[OrderOut], int]:
    q = select(Order).where(Order.establishment_id == est_id)
    if statuses:
        q = q.where(Order.status.in_(statuses))
    if session_id:
        q = q.where(Order.session_id == session_id)
    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
    rows = (await db.execute(q.order_by(Order.created_at).limit(limit).offset(offset))).unique().scalars().all()
    return [order_out(o) for o in rows], int(total)


async def update_status(db: AsyncSession, ctx: StaffCtx, order_id: uuid.UUID, target: OrderStatus,
                        reason: str | None, expected_version: int | None) -> OrderOut:
    o = (await db.execute(select(Order).where(Order.id == order_id, Order.establishment_id == ctx.establishment_id)
                          .with_for_update(of=Order).execution_options(populate_existing=True))).unique().scalar_one_or_none()
    if o is None:
        raise not_found("Pedido")
    if target == OrderStatus.CANCELADO:
        if not ctx.can(Perm.ORDERS_CANCEL):
            raise AppError(403, "forbidden", "Apenas caixa ou administrador podem cancelar pedidos.")
        if not reason:
            raise AppError(422, "reason_required", "Informe o motivo do cancelamento.")
    if expected_version is not None and expected_version != o.version:
        raise AppError(409, "stale_version", "O pedido foi alterado por outra pessoa.", {"current_version": o.version})
    ensure_transition(ORDER_TRANSITIONS, o.status, target, "Pedido")
    db.add(OrderStatusHistory(order_id=o.id, from_status=o.status.value, to_status=target.value,
                              changed_by_id=ctx.user.id, reason=reason))
    o.status = target
    o.version += 1
    # O chamado NOVO_PEDIDO acompanha o pedido: concluído quando entregue/cancelado.
    reqs = (await db.execute(select(ServiceRequest).where(ServiceRequest.order_id == o.id).with_for_update(
        of=ServiceRequest))).unique().scalars().all()
    for r in reqs:
        if r.status in (RequestStatus.CONCLUIDA, RequestStatus.CANCELADA):
            continue
        if target in (OrderStatus.ENTREGUE, OrderStatus.CANCELADO):
            r.status = RequestStatus.CONCLUIDA if target == OrderStatus.ENTREGUE else RequestStatus.CANCELADA
            r.completed_at = func.now()
        elif r.status == RequestStatus.PENDENTE:
            r.status = RequestStatus.EM_ATENDIMENTO
            r.assigned_to_id = r.assigned_to_id or ctx.user.id
            r.claimed_at = func.now()
        else:
            continue
        r.version += 1
    await db.flush()
    o = await _load(db, o.id)
    audit(db, establishment_id=ctx.establishment_id, actor_id=ctx.user.id, action="order.status",
          target_type="order", target_id=o.id, details={"to": target.value, "reason": reason})
    out = _emit(db, o)
    for r in reqs:
        r2 = (await db.execute(select(ServiceRequest).where(ServiceRequest.id == r.id)
                               .execution_options(populate_existing=True))).unique().scalar_one()
        emit(db, ctx.establishment_id, "request.updated", {"request": request_out(r2).model_dump(mode="json")},
             session_id=o.session_id, audience=(STAFF, SESSION))
    table = await db.get(DiningTable, o.table_id)
    assert table is not None
    await table_svc.emit_table(db, table)
    return out
