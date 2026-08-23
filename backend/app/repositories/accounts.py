"""Account repository."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Account


class AccountRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, account_id: str) -> Account | None:
        result = await self.session.execute(select(Account).where(Account.id == account_id))
        return result.scalar_one_or_none()

    async def list_active(self) -> list[Account]:
        result = await self.session.execute(select(Account).where(Account.status == "active").order_by(Account.id))
        return list(result.scalars().all())
