"""Conversation thread endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependency import get_db_session
from app.repositories import ConversationMessageRepository, ConversationThreadRepository
from app.schemas.auth import UserContext
from app.security.auth import get_current_user


router = APIRouter()


@router.get("/{thread_id}")
async def get_thread(
    thread_id: str,
    user: UserContext = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    thread = await ConversationThreadRepository(session).get_for_user(thread_id, user)
    if thread is None:
        raise HTTPException(status_code=404, detail="Thread not found")
    return {
        "thread_id": thread.id,
        "user_id": thread.user_id,
        "account_id": thread.account_id,
        "created_at": thread.created_at,
        "updated_at": thread.updated_at,
    }


@router.get("/{thread_id}/messages")
async def get_thread_messages(
    thread_id: str,
    user: UserContext = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    thread = await ConversationThreadRepository(session).get_for_user(thread_id, user)
    if thread is None:
        raise HTTPException(status_code=404, detail="Thread not found")
    messages = await ConversationMessageRepository(session).list_for_thread(thread_id, user)
    return {
        "thread_id": thread_id,
        "messages": [
            {
                "message_id": str(message.id),
                "role": message.role,
                "content": message.content,
                "created_at": message.created_at,
            }
            for message in messages
        ],
    }
