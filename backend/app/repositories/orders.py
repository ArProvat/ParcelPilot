"""Order repository with account-scoped lookup methods."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Order
from app.schemas.auth import UserContext
from app.security.authorization import accessible_account_ids, require_permission


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

    async def get_accessible(self, order_id: str, user: UserContext) -> Order | None:
        require_permission(user, "orders:read")
        stmt = select(Order).where(Order.id == order_id)
        allowed_accounts = accessible_account_ids(user)
        if allowed_accounts is not None:
            if not allowed_accounts:
                return None
            stmt = stmt.where(Order.account_id.in_(allowed_accounts))

        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_accessible(self, user: UserContext) -> list[Order]:
        require_permission(user, "orders:read")
        stmt = select(Order).order_by(Order.booked_at.desc())
        allowed_accounts = accessible_account_ids(user)
        if allowed_accounts is not None:
            if not allowed_accounts:
                return []
            stmt = stmt.where(Order.account_id.in_(allowed_accounts))

        result = await self.session.execute(stmt)
        return list(result.scalars().all())
