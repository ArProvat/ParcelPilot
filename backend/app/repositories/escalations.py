"""Escalation repository."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Escalation


class EscalationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, escalation: Escalation) -> Escalation:
        self.session.add(escalation)
        await self.session.flush()
        return escalation

    async def list_for_account(self, account_id: str) -> list[Escalation]:
        result = await self.session.execute(
            select(Escalation).where(Escalation.account_id == account_id).order_by(Escalation.created_at.desc())
        )
        return list(result.scalars().all())
