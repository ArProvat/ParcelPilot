"""Pending action repository for human approval workflows."""
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PendingAction


class PendingActionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, action_id: UUID) -> PendingAction | None:
        result = await self.session.execute(select(PendingAction).where(PendingAction.action_id == action_id))
        return result.scalar_one_or_none()

    async def save(self, action: PendingAction) -> PendingAction:
        self.session.add(action)
        await self.session.flush()
        return action
