"""Escalation repository."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Escalation
from app.schemas.auth import UserContext
from app.security.authorization import AuthorizationError, can_access_account, require_permission


class EscalationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, escalation: Escalation) -> Escalation:
        self.session.add(escalation)
        await self.session.flush()
        return escalation

    async def get_by_idempotency_key(self, idempotency_key: str) -> Escalation | None:
        result = await self.session.execute(
            select(Escalation).where(Escalation.idempotency_key == idempotency_key)
        )
        return result.scalar_one_or_none()

    async def create_authorized(self, escalation: Escalation, user: UserContext) -> Escalation:
        require_permission(user, "escalations:create")
        if not can_access_account(user, escalation.account_id):
            raise AuthorizationError("Cannot create escalation for inaccessible account.")
        return await self.create(escalation)

    async def list_for_account(self, account_id: str) -> list[Escalation]:
        result = await self.session.execute(
            select(Escalation).where(Escalation.account_id == account_id).order_by(Escalation.created_at.desc())
        )
        return list(result.scalars().all())
