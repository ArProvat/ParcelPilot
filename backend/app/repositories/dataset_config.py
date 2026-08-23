"""Dataset configuration repository."""
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DatasetConfig


class DatasetConfigRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_current(self) -> DatasetConfig | None:
        result = await self.session.execute(select(DatasetConfig).where(DatasetConfig.id == 1))
        return result.scalar_one_or_none()

    async def snapshot_time(self) -> datetime:
        config = await self.get_current()
        if config is None:
            raise LookupError("Dataset configuration has not been imported.")
        return config.snapshot_at
