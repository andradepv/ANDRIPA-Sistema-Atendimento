"""add_table_awaiting_and_order_in_progress_statuses

Revision ID: 664b5c74a493
Revises: c8a7dac74585
Create Date: 2026-11-22 17:47:16.899315
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "664b5c74a493"
down_revision = "c8a7dac74585"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Permite session_id nulo em service_requests (para LIBERAR_MESA antes de abrir sessão)
    op.alter_column("service_requests", "session_id", nullable=True)

    # 2. Atualiza CHECK constraint de status da mesa (inclui AGUARDANDO_LIBERACAO)
    op.execute("ALTER TABLE tables DROP CONSTRAINT IF EXISTS ck_tables_table_status")
    op.execute(
        """
        ALTER TABLE tables
        ADD CONSTRAINT ck_tables_table_status
        CHECK (status IN ('LIVRE', 'AGUARDANDO_LIBERACAO', 'OCUPADA'))
        """
    )

    # 3. Atualiza CHECK constraint de tipo da solicitação (inclui LIBERAR_MESA)
    op.execute("ALTER TABLE service_requests DROP CONSTRAINT IF EXISTS ck_service_requests_request_type")
    op.execute(
        """
        ALTER TABLE service_requests
        ADD CONSTRAINT ck_service_requests_request_type
        CHECK (type IN ('LIBERAR_MESA', 'CHAMAR_ATENDENTE', 'NOVO_PEDIDO', 'PEDIR_CONTA'))
        """
    )

    # 4. Atualiza CHECK constraint de status da solicitação (garante EM_ATENDIMENTO)
    op.execute("ALTER TABLE service_requests DROP CONSTRAINT IF EXISTS ck_service_requests_request_status")
    op.execute(
        """
        ALTER TABLE service_requests
        ADD CONSTRAINT ck_service_requests_request_status
        CHECK (status IN ('PENDENTE', 'EM_ATENDIMENTO', 'CONCLUIDA', 'CANCELADA'))
        """
    )

    # 5. Atualiza índices únicos parciais
    op.execute("DROP INDEX IF EXISTS uq_active_request_per_type")
    op.execute(
        """
        CREATE UNIQUE INDEX uq_active_request_per_type
        ON service_requests (session_id, type)
        WHERE status IN ('PENDENTE', 'EM_ATENDIMENTO')
          AND session_id IS NOT NULL
          AND type <> 'NOVO_PEDIDO'
        """
    )

    op.execute("DROP INDEX IF EXISTS uq_active_unlock_per_table")
    op.execute(
        """
        CREATE UNIQUE INDEX uq_active_unlock_per_table
        ON service_requests (table_id)
        WHERE status = 'PENDENTE'
          AND type = 'LIBERAR_MESA'
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_active_unlock_per_table")
    op.execute("DROP INDEX IF EXISTS uq_active_request_per_type")

    op.execute("DELETE FROM service_requests WHERE session_id IS NULL OR type = 'LIBERAR_MESA'")
    op.execute("UPDATE tables SET status = 'LIVRE' WHERE status = 'AGUARDANDO_LIBERACAO'")
    op.execute("UPDATE service_requests SET status = 'CONCLUIDA' WHERE status = 'EM_ATENDIMENTO'")

    op.execute("ALTER TABLE service_requests DROP CONSTRAINT IF EXISTS ck_service_requests_request_status")
    op.execute(
        """
        ALTER TABLE service_requests
        ADD CONSTRAINT ck_service_requests_request_status
        CHECK (status IN ('PENDENTE', 'CONCLUIDA', 'CANCELADA'))
        """
    )

    op.execute("ALTER TABLE service_requests DROP CONSTRAINT IF EXISTS ck_service_requests_request_type")
    op.execute(
        """
        ALTER TABLE service_requests
        ADD CONSTRAINT ck_service_requests_request_type
        CHECK (type IN ('CHAMAR_ATENDENTE', 'NOVO_PEDIDO', 'PEDIR_CONTA'))
        """
    )

    op.execute("ALTER TABLE tables DROP CONSTRAINT IF EXISTS ck_tables_table_status")
    op.execute(
        """
        ALTER TABLE tables
        ADD CONSTRAINT ck_tables_table_status
        CHECK (status IN ('LIVRE', 'OCUPADA'))
        """
    )

    op.alter_column("service_requests", "session_id", nullable=False)
