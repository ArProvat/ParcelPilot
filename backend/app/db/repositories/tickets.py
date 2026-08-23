"""Ticket repository with account-scoped lookup methods."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Ticket


class TicketRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_for_account(self, ticket_id: str, account_id: str) -> Ticket | None:
        stmt = (
            select(Ticket)
            .where(Ticket.id == ticket_id)
            .where(Ticket.account_id == account_id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_open_for_account(self, account_id: str) -> list[Ticket]:
        result = await self.session.execute(
            select(Ticket)
            .where(Ticket.account_id == account_id)
            .where(Ticket.status == "open")
            .order_by(Ticket.created_at.desc())
        )
        return list(result.scalars().all())
