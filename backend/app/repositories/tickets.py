"""Ticket repository with account-scoped lookup methods."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Ticket
from app.schemas.auth import UserContext
from app.security.authorization import accessible_account_ids, require_permission


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

    async def get_accessible(self, ticket_id: str, user: UserContext) -> Ticket | None:
        require_permission(user, "tickets:read")
        stmt = select(Ticket).where(Ticket.id == ticket_id)
        allowed_accounts = accessible_account_ids(user)
        if allowed_accounts is not None:
            if not allowed_accounts:
                return None
            stmt = stmt.where(Ticket.account_id.in_(allowed_accounts))

        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_open_accessible(self, user: UserContext) -> list[Ticket]:
        require_permission(user, "tickets:read")
        stmt = select(Ticket).where(Ticket.status == "open").order_by(Ticket.created_at.desc())
        allowed_accounts = accessible_account_ids(user)
        if allowed_accounts is not None:
            if not allowed_accounts:
                return []
            stmt = stmt.where(Ticket.account_id.in_(allowed_accounts))

        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_accessible(self, user: UserContext) -> list[Ticket]:
        require_permission(user, "tickets:read")
        stmt = select(Ticket).order_by(Ticket.created_at.desc())
        allowed_accounts = accessible_account_ids(user)
        if allowed_accounts is not None:
            if not allowed_accounts:
                return []
            stmt = stmt.where(Ticket.account_id.in_(allowed_accounts))

        result = await self.session.execute(stmt)
        return list(result.scalars().all())
