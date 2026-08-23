"""Audit event repository."""
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditEvent


class AuditEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record(
        self,
        *,
        event_type: str,
        user_id: str | None,
        account_id: str | None,
        thread_id: str | None,
        resource_type: str | None,
        resource_id: str | None,
        tool_name: str | None,
        payload: dict[str, Any],
        created_at: datetime,
    ) -> AuditEvent:
        event = AuditEvent(
            event_type=event_type,
            user_id=user_id,
            account_id=account_id,
            thread_id=thread_id,
            resource_type=resource_type,
            resource_id=resource_id,
            tool_name=tool_name,
            payload=payload,
            created_at=created_at,
        )
        self.session.add(event)
        await self.session.flush()
        return event
