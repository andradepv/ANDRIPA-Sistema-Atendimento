"""esquema inicial

Revision ID: 0001
Revises: 
Create Date: 2026-10-23 03:13:03.143511
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SEQUENCE IF NOT EXISTS order_number_seq START 1001")
    op.create_table('establishments',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('timezone', sa.String(length=64), nullable=False),
    sa.Column('join_code_required', sa.Boolean(), nullable=False),
    sa.Column('orders_enabled', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_establishments'))
    )
    op.create_table('idempotency_keys',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('scope', sa.String(length=120), nullable=False),
    sa.Column('key', sa.String(length=80), nullable=False),
    sa.Column('request_hash', sa.String(length=64), nullable=False),
    sa.Column('status_code', sa.Integer(), nullable=False),
    sa.Column('response', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_idempotency_keys')),
    sa.UniqueConstraint('scope', 'key', name='uq_idempotency_scope_key')
    )
    op.create_table('outbox_events',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('establishment_id', sa.UUID(), nullable=False),
    sa.Column('session_id', sa.UUID(), nullable=True),
    sa.Column('type', sa.String(length=64), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_outbox_events'))
    )
    op.create_index('ix_outbox_unpublished', 'outbox_events', ['id'], unique=False, postgresql_where=sa.text('published_at IS NULL'))
    op.create_table('categories',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('establishment_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=80), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['establishment_id'], ['establishments.id'], name=op.f('fk_categories_establishment_id_establishments'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_categories')),
    sa.UniqueConstraint('establishment_id', 'name', name='uq_categories_est_name')
    )
    op.create_index(op.f('ix_categories_establishment_id'), 'categories', ['establishment_id'], unique=False)
    op.create_table('coupons',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('establishment_id', sa.UUID(), nullable=False),
    sa.Column('code', sa.String(length=32), nullable=False),
    sa.Column('description', sa.String(length=280), nullable=True),
    sa.Column('discount_type', sa.Enum('PERCENT', 'FIXED', name='discount_type', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('value', sa.Integer(), nullable=False),
    sa.Column('min_order_cents', sa.Integer(), nullable=False),
    sa.Column('max_uses', sa.Integer(), nullable=True),
    sa.Column('uses_count', sa.Integer(), nullable=False),
    sa.Column('starts_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('ends_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("discount_type <> 'PERCENT' OR value <= 100", name=op.f('ck_coupons_percent_max')),
    sa.CheckConstraint('ends_at > starts_at', name=op.f('ck_coupons_period_valid')),
    sa.CheckConstraint('max_uses IS NULL OR uses_count <= max_uses', name=op.f('ck_coupons_uses_within_limit')),
    sa.CheckConstraint('value > 0', name=op.f('ck_coupons_value_positive')),
    sa.ForeignKeyConstraint(['establishment_id'], ['establishments.id'], name=op.f('fk_coupons_establishment_id_establishments'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_coupons')),
    sa.UniqueConstraint('establishment_id', 'code', name='uq_coupons_est_code')
    )
    op.create_index(op.f('ix_coupons_establishment_id'), 'coupons', ['establishment_id'], unique=False)
    op.create_table('promotions',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('establishment_id', sa.UUID(), nullable=False),
    sa.Column('kind', sa.Enum('BANNER', 'EVENTO', 'CAMPANHA', name='promotion_kind', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('title', sa.String(length=120), nullable=False),
    sa.Column('description', sa.String(length=1000), nullable=True),
    sa.Column('image_url', sa.String(length=500), nullable=True),
    sa.Column('conditions', sa.String(length=500), nullable=True),
    sa.Column('starts_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('ends_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('ends_at > starts_at', name=op.f('ck_promotions_period_valid')),
    sa.ForeignKeyConstraint(['establishment_id'], ['establishments.id'], name=op.f('fk_promotions_establishment_id_establishments'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_promotions'))
    )
    op.create_index(op.f('ix_promotions_establishment_id'), 'promotions', ['establishment_id'], unique=False)
    op.create_table('push_subscriptions',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('establishment_id', sa.UUID(), nullable=False),
    sa.Column('endpoint', sa.String(length=1000), nullable=False),
    sa.Column('p256dh', sa.String(length=200), nullable=False),
    sa.Column('auth', sa.String(length=100), nullable=False),
    sa.Column('consent_marketing', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_success_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('failure_count', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['establishment_id'], ['establishments.id'], name=op.f('fk_push_subscriptions_establishment_id_establishments'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_push_subscriptions')),
    sa.UniqueConstraint('endpoint', name=op.f('uq_push_subscriptions_endpoint'))
    )
    op.create_index(op.f('ix_push_subscriptions_establishment_id'), 'push_subscriptions', ['establishment_id'], unique=False)
    op.create_table('tables',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('establishment_id', sa.UUID(), nullable=False),
    sa.Column('number', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=80), nullable=True),
    sa.Column('public_code', sa.String(length=32), nullable=False),
    sa.Column('status', sa.Enum('LIVRE', 'OCUPADA', 'ENCERRAMENTO_SOLICITADO', name='table_status', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('current_session_id', sa.UUID(), nullable=True),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('number > 0', name=op.f('ck_tables_number_positive')),
    sa.ForeignKeyConstraint(['establishment_id'], ['establishments.id'], name=op.f('fk_tables_establishment_id_establishments'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_tables')),
    sa.UniqueConstraint('establishment_id', 'number', name='uq_tables_est_number'),
    sa.UniqueConstraint('public_code', name=op.f('uq_tables_public_code'))
    )
    op.create_index(op.f('ix_tables_establishment_id'), 'tables', ['establishment_id'], unique=False)
    op.create_table('users',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('establishment_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('email', sa.String(length=254), nullable=False),
    sa.Column('role', sa.Enum('ADMIN', 'CAIXA', 'ATENDENTE', name='user_role', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('pin_hash', sa.String(length=255), nullable=True),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['establishment_id'], ['establishments.id'], name=op.f('fk_users_establishment_id_establishments'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_users')),
    sa.UniqueConstraint('email', name=op.f('uq_users_email'))
    )
    op.create_index(op.f('ix_users_establishment_id'), 'users', ['establishment_id'], unique=False)
    op.create_table('audit_logs',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('establishment_id', sa.UUID(), nullable=False),
    sa.Column('actor_id', sa.UUID(), nullable=True),
    sa.Column('actor_kind', sa.String(length=16), nullable=False),
    sa.Column('action', sa.String(length=64), nullable=False),
    sa.Column('target_type', sa.String(length=32), nullable=True),
    sa.Column('target_id', sa.String(length=64), nullable=True),
    sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('ip', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['actor_id'], ['users.id'], name=op.f('fk_audit_logs_actor_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_logs'))
    )
    op.create_index('ix_audit_logs_est_created', 'audit_logs', ['establishment_id', 'created_at'], unique=False)
    op.create_table('products',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('establishment_id', sa.UUID(), nullable=False),
    sa.Column('category_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('description', sa.String(length=1000), nullable=True),
    sa.Column('price_cents', sa.Integer(), nullable=False),
    sa.Column('image_url', sa.String(length=500), nullable=True),
    sa.Column('available', sa.Boolean(), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('price_cents >= 0', name=op.f('ck_products_price_non_negative')),
    sa.ForeignKeyConstraint(['category_id'], ['categories.id'], name=op.f('fk_products_category_id_categories'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['establishment_id'], ['establishments.id'], name=op.f('fk_products_establishment_id_establishments'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_products'))
    )
    op.create_index('ix_products_est_category', 'products', ['establishment_id', 'category_id'], unique=False)
    op.create_index(op.f('ix_products_establishment_id'), 'products', ['establishment_id'], unique=False)
    op.create_table('staff_sessions',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('csrf_token', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('user_agent', sa.String(length=255), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_staff_sessions_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_staff_sessions')),
    sa.UniqueConstraint('token_hash', name=op.f('uq_staff_sessions_token_hash'))
    )
    op.create_index(op.f('ix_staff_sessions_user_id'), 'staff_sessions', ['user_id'], unique=False)
    op.create_table('table_sessions',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('establishment_id', sa.UUID(), nullable=False),
    sa.Column('table_id', sa.UUID(), nullable=False),
    sa.Column('label', sa.String(length=80), nullable=True),
    sa.Column('status', sa.Enum('OPEN', 'CLOSED', name='session_status', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('join_code', sa.String(length=8), nullable=False),
    sa.Column('opened_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('opened_by_id', sa.UUID(), nullable=False),
    sa.Column('close_requested_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('closed_by_id', sa.UUID(), nullable=True),
    sa.Column('subtotal_cents', sa.Integer(), nullable=True),
    sa.Column('discount_cents', sa.Integer(), nullable=True),
    sa.Column('total_cents', sa.Integer(), nullable=True),
    sa.Column('payment_method', sa.String(length=32), nullable=True),
    sa.Column('coupon_id', sa.UUID(), nullable=True),
    sa.Column('close_note', sa.String(length=500), nullable=True),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['closed_by_id'], ['users.id'], name=op.f('fk_table_sessions_closed_by_id_users')),
    sa.ForeignKeyConstraint(['coupon_id'], ['coupons.id'], name=op.f('fk_table_sessions_coupon_id_coupons')),
    sa.ForeignKeyConstraint(['establishment_id'], ['establishments.id'], name=op.f('fk_table_sessions_establishment_id_establishments'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['opened_by_id'], ['users.id'], name=op.f('fk_table_sessions_opened_by_id_users')),
    sa.ForeignKeyConstraint(['table_id'], ['tables.id'], name=op.f('fk_table_sessions_table_id_tables'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_table_sessions'))
    )
    op.create_index('ix_table_sessions_est_status_opened', 'table_sessions', ['establishment_id', 'status', 'opened_at'], unique=False)
    op.create_index(op.f('ix_table_sessions_establishment_id'), 'table_sessions', ['establishment_id'], unique=False)
    op.create_index(op.f('ix_table_sessions_table_id'), 'table_sessions', ['table_id'], unique=False)
    op.create_index('uq_open_session_per_table', 'table_sessions', ['table_id'], unique=True, postgresql_where=sa.text("status = 'OPEN'"))
    op.create_table('customer_tokens',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('session_id', sa.UUID(), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['session_id'], ['table_sessions.id'], name=op.f('fk_customer_tokens_session_id_table_sessions'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_customer_tokens')),
    sa.UniqueConstraint('token_hash', name=op.f('uq_customer_tokens_token_hash'))
    )
    op.create_index(op.f('ix_customer_tokens_session_id'), 'customer_tokens', ['session_id'], unique=False)
    op.create_table('option_groups',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('product_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=80), nullable=False),
    sa.Column('min_select', sa.Integer(), nullable=False),
    sa.Column('max_select', sa.Integer(), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.CheckConstraint('min_select >= 0 AND max_select >= min_select AND max_select >= 1', name=op.f('ck_option_groups_select_range')),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], name=op.f('fk_option_groups_product_id_products'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_option_groups'))
    )
    op.create_index(op.f('ix_option_groups_product_id'), 'option_groups', ['product_id'], unique=False)
    op.create_table('orders',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('establishment_id', sa.UUID(), nullable=False),
    sa.Column('session_id', sa.UUID(), nullable=False),
    sa.Column('table_id', sa.UUID(), nullable=False),
    sa.Column('number', sa.BigInteger(), server_default=sa.text("nextval('order_number_seq')"), nullable=False),
    sa.Column('status', sa.Enum('RECEBIDO', 'EM_PREPARO', 'PRONTO', 'ENTREGUE', 'CANCELADO', name='order_status', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('origin', sa.String(length=16), nullable=False),
    sa.Column('note', sa.String(length=280), nullable=True),
    sa.Column('total_cents', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.CheckConstraint('total_cents >= 0', name=op.f('ck_orders_total_non_negative')),
    sa.ForeignKeyConstraint(['establishment_id'], ['establishments.id'], name=op.f('fk_orders_establishment_id_establishments'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['session_id'], ['table_sessions.id'], name=op.f('fk_orders_session_id_table_sessions'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['table_id'], ['tables.id'], name=op.f('fk_orders_table_id_tables')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_orders'))
    )
    op.create_index('ix_orders_est_status_created', 'orders', ['establishment_id', 'status', 'created_at'], unique=False)
    op.create_index(op.f('ix_orders_establishment_id'), 'orders', ['establishment_id'], unique=False)
    op.create_index(op.f('ix_orders_session_id'), 'orders', ['session_id'], unique=False)
    op.create_table('service_requests',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('establishment_id', sa.UUID(), nullable=False),
    sa.Column('session_id', sa.UUID(), nullable=False),
    sa.Column('table_id', sa.UUID(), nullable=False),
    sa.Column('type', sa.Enum('CHAMAR_ATENDENTE', 'NOVO_PEDIDO', 'PEDIR_CONTA', name='request_type', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('status', sa.Enum('PENDENTE', 'ASSUMIDA', 'EM_ATENDIMENTO', 'CONCLUIDA', 'CANCELADA', name='request_status', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('priority', sa.Integer(), nullable=False),
    sa.Column('note', sa.String(length=280), nullable=True),
    sa.Column('order_id', sa.UUID(), nullable=True),
    sa.Column('origin', sa.String(length=16), nullable=False),
    sa.Column('assigned_to_id', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('claimed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.CheckConstraint('priority BETWEEN 0 AND 3', name=op.f('ck_service_requests_priority_range')),
    sa.ForeignKeyConstraint(['assigned_to_id'], ['users.id'], name=op.f('fk_service_requests_assigned_to_id_users')),
    sa.ForeignKeyConstraint(['establishment_id'], ['establishments.id'], name=op.f('fk_service_requests_establishment_id_establishments'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['session_id'], ['table_sessions.id'], name=op.f('fk_service_requests_session_id_table_sessions'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['table_id'], ['tables.id'], name=op.f('fk_service_requests_table_id_tables')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_service_requests'))
    )
    op.create_index('ix_service_requests_est_status_created', 'service_requests', ['establishment_id', 'status', 'created_at'], unique=False)
    op.create_index(op.f('ix_service_requests_establishment_id'), 'service_requests', ['establishment_id'], unique=False)
    op.create_index(op.f('ix_service_requests_session_id'), 'service_requests', ['session_id'], unique=False)
    op.create_index('uq_active_request_per_type', 'service_requests', ['session_id', 'type'], unique=True, postgresql_where=sa.text("status IN ('PENDENTE','ASSUMIDA','EM_ATENDIMENTO') AND type <> 'NOVO_PEDIDO'"))
    op.create_table('order_items',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('order_id', sa.UUID(), nullable=False),
    sa.Column('product_id', sa.UUID(), nullable=False),
    sa.Column('product_name', sa.String(length=120), nullable=False),
    sa.Column('unit_price_cents', sa.Integer(), nullable=False),
    sa.Column('quantity', sa.Integer(), nullable=False),
    sa.Column('options', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('notes', sa.String(length=280), nullable=True),
    sa.Column('line_total_cents', sa.Integer(), nullable=False),
    sa.CheckConstraint('quantity BETWEEN 1 AND 50', name=op.f('ck_order_items_quantity_range')),
    sa.ForeignKeyConstraint(['order_id'], ['orders.id'], name=op.f('fk_order_items_order_id_orders'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], name=op.f('fk_order_items_product_id_products'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_order_items'))
    )
    op.create_index(op.f('ix_order_items_order_id'), 'order_items', ['order_id'], unique=False)
    op.create_table('order_status_history',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('order_id', sa.UUID(), nullable=False),
    sa.Column('from_status', sa.String(length=32), nullable=True),
    sa.Column('to_status', sa.String(length=32), nullable=False),
    sa.Column('changed_by_id', sa.UUID(), nullable=True),
    sa.Column('reason', sa.String(length=280), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['changed_by_id'], ['users.id'], name=op.f('fk_order_status_history_changed_by_id_users')),
    sa.ForeignKeyConstraint(['order_id'], ['orders.id'], name=op.f('fk_order_status_history_order_id_orders'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_order_status_history'))
    )
    op.create_index(op.f('ix_order_status_history_order_id'), 'order_status_history', ['order_id'], unique=False)
    op.create_table('product_options',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('group_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=80), nullable=False),
    sa.Column('price_cents', sa.Integer(), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.CheckConstraint('price_cents >= 0', name=op.f('ck_product_options_price_non_negative')),
    sa.ForeignKeyConstraint(['group_id'], ['option_groups.id'], name=op.f('fk_product_options_group_id_option_groups'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_product_options'))
    )
    op.create_index(op.f('ix_product_options_group_id'), 'product_options', ['group_id'], unique=False)

    # FKs circulares criadas após as tabelas.
    op.create_foreign_key('fk_tables_current_session', 'tables', 'table_sessions', ['current_session_id'], ['id'])
    op.create_foreign_key('fk_service_requests_order', 'service_requests', 'orders', ['order_id'], ['id'])

def downgrade() -> None:
    op.drop_constraint('fk_service_requests_order', 'service_requests', type_='foreignkey')
    op.drop_constraint('fk_tables_current_session', 'tables', type_='foreignkey')
    op.drop_index(op.f('ix_product_options_group_id'), table_name='product_options')
    op.drop_table('product_options')
    op.drop_index(op.f('ix_order_status_history_order_id'), table_name='order_status_history')
    op.drop_table('order_status_history')
    op.drop_index(op.f('ix_order_items_order_id'), table_name='order_items')
    op.drop_table('order_items')
    op.drop_index('uq_active_request_per_type', table_name='service_requests', postgresql_where=sa.text("status IN ('PENDENTE','ASSUMIDA','EM_ATENDIMENTO') AND type <> 'NOVO_PEDIDO'"))
    op.drop_index(op.f('ix_service_requests_session_id'), table_name='service_requests')
    op.drop_index(op.f('ix_service_requests_establishment_id'), table_name='service_requests')
    op.drop_index('ix_service_requests_est_status_created', table_name='service_requests')
    op.drop_table('service_requests')
    op.drop_index(op.f('ix_orders_session_id'), table_name='orders')
    op.drop_index(op.f('ix_orders_establishment_id'), table_name='orders')
    op.drop_index('ix_orders_est_status_created', table_name='orders')
    op.drop_table('orders')
    op.drop_index(op.f('ix_option_groups_product_id'), table_name='option_groups')
    op.drop_table('option_groups')
    op.drop_index(op.f('ix_customer_tokens_session_id'), table_name='customer_tokens')
    op.drop_table('customer_tokens')
    op.drop_index('uq_open_session_per_table', table_name='table_sessions', postgresql_where=sa.text("status = 'OPEN'"))
    op.drop_index(op.f('ix_table_sessions_table_id'), table_name='table_sessions')
    op.drop_index(op.f('ix_table_sessions_establishment_id'), table_name='table_sessions')
    op.drop_index('ix_table_sessions_est_status_opened', table_name='table_sessions')
    op.drop_table('table_sessions')
    op.drop_index(op.f('ix_staff_sessions_user_id'), table_name='staff_sessions')
    op.drop_table('staff_sessions')
    op.drop_index(op.f('ix_products_establishment_id'), table_name='products')
    op.drop_index('ix_products_est_category', table_name='products')
    op.drop_table('products')
    op.drop_index('ix_audit_logs_est_created', table_name='audit_logs')
    op.drop_table('audit_logs')
    op.drop_index(op.f('ix_users_establishment_id'), table_name='users')
    op.drop_table('users')
    op.drop_index(op.f('ix_tables_establishment_id'), table_name='tables')
    op.drop_table('tables')
    op.drop_index(op.f('ix_push_subscriptions_establishment_id'), table_name='push_subscriptions')
    op.drop_table('push_subscriptions')
    op.drop_index(op.f('ix_promotions_establishment_id'), table_name='promotions')
    op.drop_table('promotions')
    op.drop_index(op.f('ix_coupons_establishment_id'), table_name='coupons')
    op.drop_table('coupons')
    op.drop_index(op.f('ix_categories_establishment_id'), table_name='categories')
    op.drop_table('categories')
    op.drop_index('ix_outbox_unpublished', table_name='outbox_events', postgresql_where=sa.text('published_at IS NULL'))
    op.drop_table('outbox_events')
    op.drop_table('idempotency_keys')
    op.drop_table('establishments')
    op.execute("DROP SEQUENCE IF EXISTS order_number_seq")
