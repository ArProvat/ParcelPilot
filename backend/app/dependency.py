"""FastAPI dependencies."""
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession


async def get_db_session() -> AsyncIterator[AsyncSession]:
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        yield session
