from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool


class Database:
    def __init__(self) -> None:
        self.engine: AsyncEngine | None = None
        self.sessionmaker: async_sessionmaker[AsyncSession] | None = None

    def init(self, url: str, *, pool_size: int = 10, null_pool: bool = False) -> None:
        kwargs: dict = {"pool_pre_ping": True}
        if null_pool:
            kwargs["poolclass"] = NullPool
        else:
            kwargs.update(pool_size=pool_size, max_overflow=pool_size)
        self.engine = create_async_engine(url, **kwargs)
        self.sessionmaker = async_sessionmaker(self.engine, expire_on_commit=False)

    async def dispose(self) -> None:
        if self.engine is not None:
            await self.engine.dispose()

    def session(self) -> AsyncSession:
        assert self.sessionmaker is not None, "Database not initialised"
        return self.sessionmaker()


db = Database()


async def get_db() -> AsyncIterator[AsyncSession]:
    async with db.session() as session:
        yield session
