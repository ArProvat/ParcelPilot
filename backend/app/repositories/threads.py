"""Conversation thread repositories with ownership filtering."""
from datetime import datetime, timezone

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

    async def ensure_access(self, thread_id: str, user: UserContext) -> ConversationThread:
        """Return the thread if the user owns it; create it if new; raise PermissionError otherwise.

        This is the authoritative access-check for streaming.  Call it before
        invoking the agent so that cross-user thread access is denied before
        any LLM work begins.
        """
        thread = await self.get_for_user(thread_id, user)
        if thread is not None:
            return thread

        # Check whether the thread exists but belongs to another user.
        existing = await self.session.execute(
            select(ConversationThread).where(ConversationThread.id == thread_id)
        )
        if existing.scalar_one_or_none() is not None:
            raise PermissionError(f"Thread {thread_id!r} belongs to another user")

        # Create a new thread owned by this user.
        now = datetime.now(timezone.utc)
        thread = ConversationThread(
            id=thread_id,
            user_id=user.user_id,
            account_id=user.account_id,
            title=None,
            created_at=now,
            updated_at=now,
        )
        self.session.add(thread)
        await self.session.flush()
        return thread

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
