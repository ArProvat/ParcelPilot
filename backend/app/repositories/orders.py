"""Order repository with account-scoped lookup methods."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Order


class OrderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_for_account(self, order_id: str, account_id: str) -> Order | None:
        stmt = (
            select(Order)
            .where(Order.id == order_id)
            .where(Order.account_id == account_id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_account(self, account_id: str) -> list[Order]:
        result = await self.session.execute(
            select(Order).where(Order.account_id == account_id).order_by(Order.booked_at.desc())
        )
        return list(result.scalars().all())
