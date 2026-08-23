"""Chat streaming and thread endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependency import get_db_session
from app.repositories import ConversationMessageRepository, ConversationThreadRepository
from app.schemas.api import ChatRequest
from app.schemas.auth import UserContext
from app.security.auth import get_current_user
from app.services.agent_stream import AgentStreamService
from app.services.streaming import serialize_sse


router = APIRouter()


@router.post("/stream")
async def chat_stream(
    request: ChatRequest,
    user: UserContext = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    async def event_generator():
        try:
            async for event in AgentStreamService(session).stream_chat(
                thread_id=request.thread_id,
                message=request.message,
                user=user,
            ):
                yield serialize_sse(event)
        except Exception:
            from app.services.streaming import make_event

            yield serialize_sse(
                make_event(
                    request.thread_id,
                    "error",
                    {
                        "code": "AGENT_EXECUTION_FAILED",
                        "message": "The request could not be completed.",
                    },
                )
            )

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/threads/{thread_id}")
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


@router.get("/threads/{thread_id}/messages")
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
