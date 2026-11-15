"""remove o que está fora do escopo (chamado de garçom + gestão de mesas)

Retira cardápio, pedidos, cupons, promoções, notificações push e o registro de valores/pagamento da
sessão da mesa. Dados de mesas, sessões, chamados, etiquetas NFC, plantas, usuários e auditoria são mantidos.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-01 23:30:00
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- chamados: só CHAMAR_ATENDENTE e PEDIR_CONTA ---
    op.execute("DELETE FROM service_requests WHERE type = 'NOVO_PEDIDO'")
    op.drop_constraint(op.f("fk_service_requests_order"), "service_requests", type_="foreignkey")
    op.drop_column("service_requests", "order_id")
    op.drop_constraint(op.f("ck_service_requests_request_type"), "service_requests", type_="check")
    op.create_check_constraint(op.f("ck_service_requests_request_type"), "service_requests",
                               "type IN ('CHAMAR_ATENDENTE', 'PEDIR_CONTA')")
    op.drop_index("uq_active_request_per_type", table_name="service_requests",
                  postgresql_where=sa.text("status IN ('PENDENTE','ASSUMIDA','EM_ATENDIMENTO') AND type <> 'NOVO_PEDIDO'"))
    op.create_index("uq_active_request_per_type", "service_requests", ["session_id", "type"], unique=True,
                    postgresql_where=sa.text("status IN ('PENDENTE','ASSUMIDA','EM_ATENDIMENTO')"))

    # --- sessão da mesa: sem valores, desconto, cupom ou forma de pagamento ---
    op.drop_constraint(op.f("fk_table_sessions_coupon_id_coupons"), "table_sessions", type_="foreignkey")
    for col in ("subtotal_cents", "discount_cents", "total_cents", "payment_method", "coupon_id", "close_note"):
        op.drop_column("table_sessions", col)

    # --- estabelecimento: sem opção de pedidos pelo celular ---
    op.drop_column("establishments", "orders_enabled")

    # --- tabelas de venda e marketing ---
    for table in ("order_status_history", "order_items", "orders", "product_options", "option_groups",
                  "products", "categories", "coupons", "promotions", "push_subscriptions"):
        op.drop_table(table)
    op.execute("DROP SEQUENCE IF EXISTS order_number_seq")

    # --- eventos pendentes de tipos que deixaram de existir ---
    op.execute("DELETE FROM outbox_events WHERE type LIKE 'order.%' OR type LIKE 'menu.%'")


def downgrade() -> None:
    raise NotImplementedError(
        "Esta migração apaga dados de pedidos, cardápio, cupons, promoções e push de forma irreversível. "
        "Para voltar, restaure um backup anterior à revisão 0003."
    )
