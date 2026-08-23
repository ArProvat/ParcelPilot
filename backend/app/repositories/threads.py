"""Conversation thread repositories with ownership filtering."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ConversationMessage, ConversationThread
from app.schemas.auth import UserContext


class ConversationThreadRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_for_user(self, thread_id: str, user: UserContext) -> ConversationThread | None:
        stmt = select(ConversationThread).where(ConversationThread.id == thread_id)
        if user.role != "operations_admin":
            stmt = stmt.where(ConversationThread.user_id == user.user_id)

        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def save(self, thread: ConversationThread) -> ConversationThread:
        self.session.add(thread)
        await self.session.flush()
        return thread


class ConversationMessageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_for_thread(self, thread_id: str, user: UserContext) -> list[ConversationMessage]:
        stmt = (
            select(ConversationMessage)
            .join(ConversationThread, ConversationMessage.thread_id == ConversationThread.id)
            .where(ConversationMessage.thread_id == thread_id)
            .order_by(ConversationMessage.created_at)
        )
        if user.role != "operations_admin":
            stmt = stmt.where(ConversationThread.user_id == user.user_id)

        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def save(self, message: ConversationMessage) -> ConversationMessage:
        self.session.add(message)
        await self.session.flush()
        return message
