"""tags de mesa e plantas do salao

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-01 13:49:37.335431
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    
    op.create_table('floor_layouts',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('establishment_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=80), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['establishment_id'], ['establishments.id'], name=op.f('fk_floor_layouts_establishment_id_establishments'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_floor_layouts')),
    sa.UniqueConstraint('establishment_id', 'name', name='uq_floor_layouts_est_name')
    )
    op.create_index(op.f('ix_floor_layouts_establishment_id'), 'floor_layouts', ['establishment_id'], unique=False)
    op.create_index('uq_active_layout_per_est', 'floor_layouts', ['establishment_id'], unique=True, postgresql_where=sa.text('is_active'))
    op.create_table('floor_layout_items',
    sa.Column('layout_id', sa.UUID(), nullable=False),
    sa.Column('table_id', sa.UUID(), nullable=False),
    sa.Column('x', sa.Integer(), nullable=False),
    sa.Column('y', sa.Integer(), nullable=False),
    sa.CheckConstraint('x >= 0 AND x < 24 AND y >= 0 AND y < 16', name=op.f('ck_floor_layout_items_cell_in_grid')),
    sa.ForeignKeyConstraint(['layout_id'], ['floor_layouts.id'], name=op.f('fk_floor_layout_items_layout_id_floor_layouts'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['table_id'], ['tables.id'], name=op.f('fk_floor_layout_items_table_id_tables'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('layout_id', 'table_id', name=op.f('pk_floor_layout_items')),
    sa.UniqueConstraint('layout_id', 'x', 'y', name='uq_floor_item_cell')
    )
    op.create_table('table_tags',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('establishment_id', sa.UUID(), nullable=False),
    sa.Column('table_id', sa.UUID(), nullable=False),
    sa.Column('status', sa.Enum('PENDENTE', 'GRAVANDO', 'GRAVADA', 'TRAVADA', 'FALHA', 'SUBSTITUIDA', name='tag_status', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('url', sa.String(length=500), nullable=False),
    sa.Column('uid', sa.String(length=32), nullable=True),
    sa.Column('error', sa.String(length=280), nullable=True),
    sa.Column('started_by_id', sa.UUID(), nullable=False),
    sa.Column('lock_authorized_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('written_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('locked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['establishment_id'], ['establishments.id'], name=op.f('fk_table_tags_establishment_id_establishments'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['started_by_id'], ['users.id'], name=op.f('fk_table_tags_started_by_id_users')),
    sa.ForeignKeyConstraint(['table_id'], ['tables.id'], name=op.f('fk_table_tags_table_id_tables'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_table_tags'))
    )
    op.create_index('ix_table_tags_est_updated', 'table_tags', ['establishment_id', 'updated_at'], unique=False)
    op.create_index(op.f('ix_table_tags_establishment_id'), 'table_tags', ['establishment_id'], unique=False)
    op.create_index(op.f('ix_table_tags_table_id'), 'table_tags', ['table_id'], unique=False)
    op.create_index('uq_live_tag_per_table', 'table_tags', ['table_id'], unique=True, postgresql_where=sa.text("status IN ('PENDENTE','GRAVANDO','GRAVADA','TRAVADA')"))
    op.create_index('uq_tag_uid_in_use', 'table_tags', ['establishment_id', 'uid'], unique=True, postgresql_where=sa.text("uid IS NOT NULL AND status IN ('GRAVADA','TRAVADA')"))


    # Estabelecimentos existentes ganham a planta "Padrão" (ativa), com as mesas ativas em grade de 12 colunas.
    op.execute("""
        INSERT INTO floor_layouts (id, establishment_id, name, is_active, version)
        SELECT gen_random_uuid(), e.id, 'Padrão', true, 1 FROM establishments e
    """)
    op.execute("""
        INSERT INTO floor_layout_items (layout_id, table_id, x, y)
        SELECT l.id, t.id, (t.rn - 1) % 12, (t.rn - 1) / 12
        FROM (SELECT id, establishment_id,
                     row_number() OVER (PARTITION BY establishment_id ORDER BY number) AS rn
              FROM tables WHERE active) t
        JOIN floor_layouts l ON l.establishment_id = t.establishment_id AND l.is_active
        WHERE t.rn <= 192
    """)


def downgrade() -> None:
    
    op.drop_index('uq_tag_uid_in_use', table_name='table_tags', postgresql_where=sa.text("uid IS NOT NULL AND status IN ('GRAVADA','TRAVADA')"))
    op.drop_index('uq_live_tag_per_table', table_name='table_tags', postgresql_where=sa.text("status IN ('PENDENTE','GRAVANDO','GRAVADA','TRAVADA')"))
    op.drop_index(op.f('ix_table_tags_table_id'), table_name='table_tags')
    op.drop_index(op.f('ix_table_tags_establishment_id'), table_name='table_tags')
    op.drop_index('ix_table_tags_est_updated', table_name='table_tags')
    op.drop_table('table_tags')
    op.drop_table('floor_layout_items')
    op.drop_index('uq_active_layout_per_est', table_name='floor_layouts', postgresql_where=sa.text('is_active'))
    op.drop_index(op.f('ix_floor_layouts_establishment_id'), table_name='floor_layouts')
    op.drop_table('floor_layouts')

