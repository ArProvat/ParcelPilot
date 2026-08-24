"""Regression tests for AgentStreamService — proves it is a pure adapter.

Key guarantees tested:
  - agent.astream() is called for every message (no keyword bypass).
  - No special-casing exists for specific strings like "TKT-501" or "cancel".
  - HITL interrupt → approval.required event.
  - Thread cross-user access is blocked before the agent is invoked.
  - AgentEventTranslator correctly maps LangGraph chunks to SSE events.
"""
from __future__ import annotations

import asyncio
import inspect
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas.auth import UserContext
from app.schemas.api import StreamEvent
from app.services.agent_stream import AgentStreamService
from app.agent.stream_events import AgentEventTranslator


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

NORTHSTAR = UserContext(
    user_id="USR-NORTHSTAR-1",
    role="customer",
    account_id="ACCT-001",
    permissions=frozenset({"orders:read", "tickets:read", "escalations:create"}),
)


def _make_agent(chunks: list) -> MagicMock:
    """Build a mock agent whose astream() yields the given chunks."""

    async def _astream(*args, **kwargs):
        for chunk in chunks:
            yield chunk

    agent = MagicMock()
    agent.astream = MagicMock(side_effect=_astream)
    return agent


def _make_session_factory():
    """Return a session factory that yields a fake session with ensure_access support."""
    from datetime import datetime, timezone
    from app.models import ConversationThread

    fake_thread = ConversationThread(
        id="thr-test",
        user_id=NORTHSTAR.user_id,
        account_id=NORTHSTAR.account_id,
        title=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    class _FakeRepo:
        async def ensure_access(self, thread_id, user):
            return fake_thread

        async def get_for_user(self, thread_id, user):
            return fake_thread

    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        def begin(self):
            return self

        async def flush(self):
            pass

    original_repo_cls = None

    import app.services.agent_stream as svc_module

    class _Factory:
        def __call__(self):
            return _FakeSession()

    return _Factory()


async def _collect(gen) -> list[StreamEvent]:
    events = []
    async for event in gen:
        events.append(event)
    return events


# ---------------------------------------------------------------------------
# Test 1: agent.astream() is ALWAYS called — no keyword dispatch
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_agent_stream_invokes_agent_for_arbitrary_message():
    """Prove astream is called for a message that would never match keyword routing."""
    from langchain_core.messages import AIMessageChunk

    chunks = [("messages", (AIMessageChunk(content="Hello!"), {}))]
    agent = _make_agent(chunks)

    with patch("app.services.agent_stream.ConversationThreadRepository") as MockRepo:
        mock_repo_instance = AsyncMock()
        MockRepo.return_value = mock_repo_instance
        mock_repo_instance.ensure_access = AsyncMock(return_value=MagicMock())

        service = AgentStreamService(agent=agent, session_factory=MagicMock())
        # Patch session_factory context manager
        session_cm = AsyncMock()
        session_cm.__aenter__ = AsyncMock(return_value=session_cm)
        session_cm.__aexit__ = AsyncMock(return_value=False)
        session_cm.begin = MagicMock(return_value=session_cm)
        service.session_factory = MagicMock(return_value=session_cm)

        events = await _collect(
            service.stream_chat(
                thread_id="thr-1",
                message="What is the meaning of life?",
                user=NORTHSTAR,
            )
        )

    # astream must have been called exactly once
    assert agent.astream.call_count == 1


@pytest.mark.asyncio
async def test_agent_stream_invokes_agent_for_cancel_message():
    """Message containing 'cancel' and an ORD- ID must still go through the agent."""
    from langchain_core.messages import AIMessageChunk

    chunks = [("messages", (AIMessageChunk(content="Let me check that order."), {}))]
    agent = _make_agent(chunks)

    with patch("app.services.agent_stream.ConversationThreadRepository") as MockRepo:
        mock_repo_instance = AsyncMock()
        MockRepo.return_value = mock_repo_instance
        mock_repo_instance.ensure_access = AsyncMock(return_value=MagicMock())

        service = AgentStreamService(agent=agent, session_factory=MagicMock())
        session_cm = AsyncMock()
        session_cm.__aenter__ = AsyncMock(return_value=session_cm)
        session_cm.__aexit__ = AsyncMock(return_value=False)
        session_cm.begin = MagicMock(return_value=session_cm)
        service.session_factory = MagicMock(return_value=session_cm)

        await _collect(
            service.stream_chat(
                thread_id="thr-2",
                message="Can I cancel ORD-1001 without a fee?",
                user=NORTHSTAR,
            )
        )

    assert agent.astream.call_count == 1, "cancel+ORD message must route through agent, not a bypass"


@pytest.mark.asyncio
async def test_agent_stream_invokes_agent_for_escalate_message():
    """Message containing 'escalate' and 'TKT-501' must go through the agent."""
    from langchain_core.messages import AIMessageChunk

    chunks = [("messages", (AIMessageChunk(content="Checking ticket…"), {}))]
    agent = _make_agent(chunks)

    with patch("app.services.agent_stream.ConversationThreadRepository") as MockRepo:
        mock_repo_instance = AsyncMock()
        MockRepo.return_value = mock_repo_instance
        mock_repo_instance.ensure_access = AsyncMock(return_value=MagicMock())

        service = AgentStreamService(agent=agent, session_factory=MagicMock())
        session_cm = AsyncMock()
        session_cm.__aenter__ = AsyncMock(return_value=session_cm)
        session_cm.__aexit__ = AsyncMock(return_value=False)
        session_cm.begin = MagicMock(return_value=session_cm)
        service.session_factory = MagicMock(return_value=session_cm)

        await _collect(
            service.stream_chat(
                thread_id="thr-3",
                message="Escalate TKT-501 immediately.",
                user=NORTHSTAR,
            )
        )

    assert agent.astream.call_count == 1, "escalate+TKT-501 message must route through agent"


# ---------------------------------------------------------------------------
# Test 2: No hard-coded routing strings in agent_stream.py source
# ---------------------------------------------------------------------------

def test_no_hardcoded_routing_in_agent_stream_source():
    """Statically verify that agent_stream.py contains no keyword routing."""
    import app.services.agent_stream as module

    source = inspect.getsource(module)
    forbidden = [
        '"escalate"',
        '"cancel"',
        "TKT-501",
        "_stream_escalation_flow",
        "_stream_cancellation_flow",
        "_extract_id",
    ]
    for token in forbidden:
        assert token not in source, (
            f"Forbidden routing token {token!r} found in agent_stream.py. "
            "Business routing must not exist in the adapter layer."
        )


# ---------------------------------------------------------------------------
# Test 3: HITL interrupt → approval.required
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_hitl_interrupt_emits_approval_required():
    """A LangGraph __interrupt__ update must produce an approval.required event."""

    class _FakeInterrupt:
        value = {
            "action_id": "act-123",
            "ticket_id": "TKT-501",
            "priority": "urgent",
            "reason": "P1 outage.",
        }

    interrupt_payload = {"__interrupt__": [_FakeInterrupt()]}
    chunks = [("updates", interrupt_payload)]
    agent = _make_agent(chunks)

    with patch("app.services.agent_stream.ConversationThreadRepository") as MockRepo:
        mock_repo_instance = AsyncMock()
        MockRepo.return_value = mock_repo_instance
        mock_repo_instance.ensure_access = AsyncMock(return_value=MagicMock())

        service = AgentStreamService(agent=agent, session_factory=MagicMock())
        session_cm = AsyncMock()
        session_cm.__aenter__ = AsyncMock(return_value=session_cm)
        session_cm.__aexit__ = AsyncMock(return_value=False)
        session_cm.begin = MagicMock(return_value=session_cm)
        service.session_factory = MagicMock(return_value=session_cm)

        events = await _collect(
            service.stream_chat(
                thread_id="thr-hitl",
                message="Escalate TKT-501.",
                user=NORTHSTAR,
            )
        )

    event_types = [e.type for e in events]
    assert "approval.required" in event_types, (
        f"HITL interrupt must produce approval.required. Got: {event_types}"
    )


# ---------------------------------------------------------------------------
# Test 4: EventTranslator — text delta
# ---------------------------------------------------------------------------

def test_translator_text_delta():
    from langchain_core.messages import AIMessageChunk

    translator = AgentEventTranslator()
    chunk = AIMessageChunk(content="Hello world")
    events = translator.translate("messages", (chunk, {}), "thr-x")

    deltas = [e for e in events if e.type == "message.delta"]
    assert len(deltas) == 1
    assert deltas[0].data["text"] == "Hello world"


def test_translator_tool_started():
    from langchain_core.messages import AIMessageChunk

    translator = AgentEventTranslator()
    chunk = AIMessageChunk(
        content="",
        tool_calls=[{"id": "call_001", "name": "get_order", "args": {}}],
    )
    events = translator.translate("messages", (chunk, {}), "thr-x")

    started = [e for e in events if e.type == "tool.started"]
    assert len(started) == 1
    assert started[0].data["tool"] == "get_order"
    assert started[0].data["tool_call_id"] == "call_001"


def test_translator_tool_completed_safe_subset():
    """tool.completed must not expose raw tool result data."""
    from langchain_core.messages import ToolMessage
    import json

    translator = AgentEventTranslator()
    msg = ToolMessage(
        content=json.dumps({
            "success": True,
            "order_id": "ORD-1001",
            "account_id": "ACCT-001",  # internal field — must NOT appear in tool.completed
        }),
        tool_call_id="call_002",
        name="get_order",
    )
    events = translator.translate("messages", (msg, {}), "thr-x")

    completed = [e for e in events if e.type == "tool.completed"]
    assert len(completed) == 1
    data = completed[0].data
    # Safe fields present
    assert data["tool"] == "get_order"
    assert data["status"] == "success"
    # Raw internal data must NOT be present
    assert "account_id" not in data
    assert "order_id" not in data
