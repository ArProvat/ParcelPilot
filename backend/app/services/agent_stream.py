"""Agent-facing stream service — pure adapter between LangGraph and SSE protocol.

This service has exactly these responsibilities:
  1. Validate thread/user access (via repository)
  2. Build a trusted runtime config from the authenticated UserContext
  3. Invoke the shared LangGraph agent
  4. Translate LangGraph stream items into public SSE events
  5. Detect HITL graph interrupts → approval.required event
  6. Handle errors and cancellation

It does NOT contain business logic, keyword routing, or policy decisions.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from collections.abc import Callable
from typing import TYPE_CHECKING
from uuid import uuid4

from langchain_core.messages import HumanMessage
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from app.agent.stream_events import AgentEventTranslator
from app.repositories.threads import ConversationThreadRepository
from app.schemas.api import StreamEvent
from app.schemas.auth import UserContext
from app.services.streaming import make_event

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], AsyncSession]

# LangGraph stream modes that give us token-level deltas AND node updates.
_STREAM_MODES = ["messages", "updates"]


class AgentStreamService:
    """Adapter: LangGraph streaming → ParcelPilot SSE events."""

    def __init__(
        self,
        agent,
        session_factory: SessionFactory,
        event_translator: AgentEventTranslator | None = None,
    ) -> None:
        if event_translator is None:
            from app.agent.stream_events import AgentEventTranslator

            event_translator = AgentEventTranslator()
        self.agent = agent
        self.session_factory = session_factory
        self.event_translator = event_translator

    async def stream_chat(
        self,
        *,
        thread_id: str,
        message: str,
        user: UserContext,
    ) -> AsyncIterator[StreamEvent]:
        """Stream a user message through the LangGraph agent.

        Yields ``StreamEvent`` objects; the caller serialises them to SSE.
        """
        # 1. Thread authorization / creation (before any LLM work).
        async with self.session_factory() as session:
            async with session.begin():
                repo = ConversationThreadRepository(session)
                try:
                    await repo.ensure_access(thread_id, user)
                except PermissionError:
                    yield make_event(
                        thread_id,
                        "error",
                        {"code": "FORBIDDEN", "message": "Thread belongs to another user."},
                    )
                    return

        # 2. Build trusted runtime config — user identity lives here, not in
        #    the agent graph itself.
        config = {
            "configurable": {
                "thread_id": thread_id,
                "user": user,
            }
        }
        agent_input = {"messages": [HumanMessage(content=message)]}

        # 3. message.started marks the beginning of an agent turn.
        message_id = str(uuid4())
        yield make_event(thread_id, "message.started", {"message_id": message_id})

        try:
            # 4. Stream LangGraph execution.
            async for mode_and_payload in self.agent.astream(
                agent_input,
                config=config,
                stream_mode=_STREAM_MODES,
            ):
                # astream with a list of modes yields (mode, payload) tuples.
                if isinstance(mode_and_payload, tuple) and len(mode_and_payload) == 2:
                    mode, payload = mode_and_payload
                else:
                    # Some versions emit bare dicts for the default mode.
                    mode, payload = "updates", mode_and_payload

                # 5. Detect HITL interrupt before translation.
                if mode == "updates" and isinstance(payload, dict) and "__interrupt__" in payload:
                    interrupts = payload["__interrupt__"]
                    interrupt_val = interrupts[0] if isinstance(interrupts, (list, tuple)) and interrupts else interrupts
                    for interrupt_event in self.event_translator._interrupt_events(interrupt_val, thread_id):
                        yield interrupt_event
                    continue

                # 6. Translate all other events.
                for event in self.event_translator.translate(mode, payload, thread_id):
                    yield event

        except asyncio.CancelledError:
            # Client disconnected — propagate without logging as an error.
            raise

        except Exception:
            logger.exception(
                "agent_stream_failed",
                extra={"parcelpilot": {"thread_id": thread_id, "user_id": user.user_id}},
            )
            yield make_event(
                thread_id,
                "error",
                {
                    "code": "AGENT_EXECUTION_FAILED",
                    "message": "The request could not be completed.",
                },
            )

        finally:
            # 7. message.completed closes the turn regardless of success/failure.
            yield make_event(thread_id, "message.completed", {"message_id": message_id})
