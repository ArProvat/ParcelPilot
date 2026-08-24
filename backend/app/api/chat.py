"""Chat streaming endpoint."""
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.schemas.api import ChatRequest
from app.schemas.auth import UserContext
from app.security.auth import get_current_user
from app.services.streaming import serialize_sse


router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/stream")
async def chat_stream(
    request: Request,
    body: ChatRequest,
    user: UserContext = Depends(get_current_user),
):
    """Stream a chat message through the LangGraph agent.

    The AgentStreamService is a singleton stored in ``app.state`` (initialised
    during lifespan startup).  It manages its own database sessions internally.
    """
    service = request.app.state.agent_stream_service

    async def event_generator():
        try:
            async for event in service.stream_chat(
                thread_id=body.thread_id,
                message=body.message,
                user=user,
            ):
                yield serialize_sse(event)
        except Exception:
            logger.exception(
                "chat_stream_outer_error",
                extra={"parcelpilot": {"thread_id": body.thread_id}},
            )
            from app.services.streaming import make_event

            yield serialize_sse(
                make_event(
                    body.thread_id,
                    "error",
                    {
                        "code": "AGENT_EXECUTION_FAILED",
                        "message": "The request could not be completed.",
                    },
                )
            )

    return StreamingResponse(event_generator(), media_type="text/event-stream")
