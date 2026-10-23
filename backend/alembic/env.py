from __future__ import annotations

import asyncio

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings
from app.models import Base

target_metadata = Base.metadata


def run_offline() -> None:
    context.configure(url=get_settings().database_url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def _do_run(connection) -> None:  # noqa: ANN001
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True,
                      transaction_per_migration=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_online() -> None:
    engine = create_async_engine(get_settings().database_url)
    async with engine.connect() as conn:
        # Evita duas migrações simultâneas (ex.: duas tarefas ECS subindo ao mesmo tempo).
        await conn.exec_driver_sql("SELECT pg_advisory_lock(7428301)")
        try:
            await conn.run_sync(_do_run)
            await conn.commit()
        finally:
            await conn.exec_driver_sql("SELECT pg_advisory_unlock(7428301)")
    await engine.dispose()


if context.is_offline_mode():
    run_offline()
else:
    asyncio.run(run_online())
