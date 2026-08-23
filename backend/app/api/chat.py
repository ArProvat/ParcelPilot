"""Chat streaming endpoint."""
import logging

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependency import get_db_session
from app.schemas.api import ChatRequest
from app.schemas.auth import UserContext
from app.security.auth import get_current_user
from app.services.agent_stream import AgentStreamService
from app.services.streaming import serialize_sse


router = APIRouter()
logger = logging.getLogger(__name__)


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
            logger.exception("agent_stream_failed", extra={"parcelpilot": {"thread_id": request.thread_id}})
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
