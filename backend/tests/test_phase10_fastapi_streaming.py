"""Integration tests for FastAPI chat streaming and approval protocol.

Tests use a mock agent to stay deterministic and offline (no real LLM).
The mock agent emits pre-scripted LangGraph-style stream chunks that the
real AgentEventTranslator converts to the SSE protocol events.
"""
from pathlib import Path
import json

import pytest
from httpx import ASGITransport, AsyncClient
from langchain_core.messages import AIMessageChunk, ToolMessage
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.dependency import get_db_session
from app.ingestion import load_workbook_data
from app.ingestion.workbook import import_workbook_data
from app.main import app
from app.models import Escalation
from app.retrieval import import_document_corpus
from app.agent.stream_events import AgentEventTranslator
from app.services.agent_stream import AgentStreamService


# ---------------------------------------------------------------------------
# DB fixture — same as before
# ---------------------------------------------------------------------------

@pytest.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_foreign_keys(dbapi_connection, connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    workbook = load_workbook_data(Path(__file__).resolve().parents[2] / "data" / "ParcelPilot_Assessment_Data.xlsx")
    documents_dir = Path(__file__).resolve().parents[2] / "data" / "documents"
    async with factory() as session:
        async with session.begin():
            await import_workbook_data(session, workbook)
            await import_document_corpus(session, documents_dir)

    yield factory
    await engine.dispose()


# ---------------------------------------------------------------------------
# Mock agent helpers
# ---------------------------------------------------------------------------

def _make_cancellation_chunks():
    """Yield chunks matching what a real LangGraph agent would emit for a cancellation query."""
    # tool.started — get_order
    yield ("messages", (AIMessageChunk(
        content="",
        tool_calls=[{"id": "call_001", "name": "get_order", "args": {"order_id": "ORD-1001"}}],
    ), {}))
    # tool.completed — get_order
    yield ("messages", (ToolMessage(
        content=json.dumps({"success": True, "order_id": "ORD-1001"}),
        tool_call_id="call_001",
        name="get_order",
    ), {}))
    # tool.started — evaluate_cancellation
    yield ("messages", (AIMessageChunk(
        content="",
        tool_calls=[{"id": "call_002", "name": "evaluate_cancellation", "args": {"order_id": "ORD-1001"}}],
    ), {}))
    # decision.completed — evaluate_cancellation
    yield ("messages", (ToolMessage(
        content=json.dumps({
            "success": True,
            "allowed": True,
            "fee_inr": None,
            "reason_code": "NO_FEE",
            "explanation": "No cancellation fee applies.",
        }),
        tool_call_id="call_002",
        name="evaluate_cancellation",
    ), {}))
    # source.retrieved — search_documents
    yield ("messages", (AIMessageChunk(
        content="",
        tool_calls=[{"id": "call_003", "name": "search_documents", "args": {"query": "cancellation policy"}}],
    ), {}))
    yield ("messages", (ToolMessage(
        content=json.dumps({
            "success": True,
            "evidence": [{"source_name": "Policy v3", "section": "4.2", "page": 5}],
        }),
        tool_call_id="call_003",
        name="search_documents",
    ), {}))
    # Final text delta
    yield ("messages", (AIMessageChunk(content="No cancellation fee applies."), {}))


def _make_escalation_chunks(action_id_str: str):
    """Yield chunks for an escalation query — HITL interrupt referencing a pre-proposed action."""
    yield ("messages", (AIMessageChunk(content=""), {}))

    class _FakeInterrupt:
        value = {
            "action_id": action_id_str,
            "ticket_id": "TKT-501",
            "priority": "urgent",
            "reason": "P1 breach.",
        }

    yield ("updates", {"__interrupt__": [_FakeInterrupt()]})


async def _propose_escalation(session_factory, thread_id: str, user) -> str:
    """Propose an escalation action and return its action_id string."""
    import uuid
    from app.repositories import ConversationThreadRepository
    from app.services.escalations import EscalationService
    from app.schemas.tools import CreateEscalationInput

    action_id = uuid.uuid4()
    async with session_factory() as session:
        async with session.begin():
            await ConversationThreadRepository(session).ensure_access(thread_id, user)
            result = await EscalationService(session).propose_create_escalation(
                request=CreateEscalationInput(ticket_id="TKT-501", priority="urgent", reason="P1 breach."),
                user=user,
                thread_id=thread_id,
                action_id=action_id,
            )
    return str(result.action_id)


class _MockAgent:
    """Synchronous mock agent that streams pre-scripted chunks."""

    def __init__(self, chunks_fn):
        self._chunks_fn = chunks_fn

    async def astream(self, *args, **kwargs):
        for chunk in self._chunks_fn():
            yield chunk


# ---------------------------------------------------------------------------
# Client fixture — injects mock AgentStreamService into app.state
# ---------------------------------------------------------------------------

@pytest.fixture
async def client(session_factory):
    async def override_session():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session

    # Cancellation scenario agent (default)
    cancel_agent = _MockAgent(_make_cancellation_chunks)
    app.state.agent_stream_service = AgentStreamService(
        agent=cancel_agent,
        session_factory=session_factory,
        event_translator=AgentEventTranslator(),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as test_client:
        yield test_client

    app.dependency_overrides.clear()
    if hasattr(app.state, "agent_stream_service"):
        del app.state.agent_stream_service


def _auth(token: str = "mock-northstar") -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _parse_sse(body: str) -> list[dict]:
    events = []
    for block in body.strip().split("\n\n"):
        lines = block.splitlines()
        data_lines = [l for l in lines if l.startswith("data: ")]
        if data_lines:
            events.append(json.loads(data_lines[0].removeprefix("data: ")))
    return events


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

async def test_mock_login_and_me(client: AsyncClient) -> None:
    login = await client.post("/api/v1/auth/mock-login", json={"user": "northstar"})
    me = await client.get("/api/v1/me", headers=_auth(login.json()["access_token"]))

    assert login.status_code == 200
    assert me.status_code == 200
    assert me.json()["account_id"] == "ACCT-001"


async def test_chat_stream_cancellation_emits_app_protocol_events(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/chat/stream",
        headers=_auth(),
        json={"thread_id": "thr-cancel", "message": "Can I cancel ORD-1001 without a fee?"},
    )
    events = _parse_sse(response.text)
    event_types = [e["type"] for e in events]

    assert response.status_code == 200
    assert "message.started" in event_types
    assert "tool.started" in event_types
    assert "decision.completed" in event_types
    assert "source.retrieved" in event_types
    assert "message.completed" in event_types
    assert all("reasoning" not in e["type"] for e in events)


async def test_escalation_stream_requires_approval_then_decision_executes(
    client: AsyncClient, session_factory
) -> None:
    from app.schemas.auth import UserContext

    northstar = UserContext(
        user_id="USR-NORTHSTAR-1",
        role="customer",
        account_id="ACCT-001",
        permissions=frozenset({"orders:read", "tickets:read", "escalations:create"}),
    )
    thread_id = "thr-escalate"

    # Invariant Step 1: Initial DB count is 0
    async with session_factory() as session:
        initial_count = await session.scalar(select(func.count()).select_from(Escalation))
    assert initial_count == 0

    # Invariant Step 2: Propose escalation & stream through agent
    action_id = await _propose_escalation(session_factory, thread_id, northstar)

    escalation_agent = _MockAgent(lambda: _make_escalation_chunks(action_id))
    app.state.agent_stream_service = AgentStreamService(
        agent=escalation_agent,
        session_factory=session_factory,
        event_translator=AgentEventTranslator(),
    )

    response = await client.post(
        "/api/v1/chat/stream",
        headers=_auth(),
        json={"thread_id": thread_id, "message": "Check TKT-501 and escalate it if needed."},
    )
    events = _parse_sse(response.text)
    approval = next(e for e in events if e["type"] == "approval.required")
    action_id = approval["data"]["action_id"]

    # Invariant Step 3: DB count MUST BE UNCHANGED (0) after interrupt / approval.required
    async with session_factory() as session:
        after_interrupt_count = await session.scalar(select(func.count()).select_from(Escalation))
    assert after_interrupt_count == 0, "Database must not mutate when approval is required"

    # Invariant Step 4: User explicitly approves the action -> re-authorize & execute
    decision = await client.post(
        "/api/v1/threads/thr-escalate/decisions",
        headers=_auth(),
        json={"action_id": action_id, "decision": "approve"},
    )

    # Invariant Step 5: DB count is now incremented to 1
    async with session_factory() as session:
        after_approval_count = await session.scalar(select(func.count()).select_from(Escalation))

    assert decision.status_code == 200
    assert decision.json()["type"] == "action.completed"
    assert after_approval_count == 1


async def test_decision_reject_does_not_create_escalation(client: AsyncClient, session_factory) -> None:
    from app.schemas.auth import UserContext

    northstar = UserContext(
        user_id="USR-NORTHSTAR-1",
        role="customer",
        account_id="ACCT-001",
        permissions=frozenset({"orders:read", "tickets:read", "escalations:create"}),
    )
    thread_id = "thr-reject"

    action_id = await _propose_escalation(session_factory, thread_id, northstar)

    escalation_agent = _MockAgent(lambda: _make_escalation_chunks(action_id))
    app.state.agent_stream_service = AgentStreamService(
        agent=escalation_agent,
        session_factory=session_factory,
        event_translator=AgentEventTranslator(),
    )

    response = await client.post(
        "/api/v1/chat/stream",
        headers=_auth(),
        json={"thread_id": thread_id, "message": "Check TKT-501 and escalate it if needed."},
    )
    approval = next(e for e in _parse_sse(response.text) if e["type"] == "approval.required")

    # Verify count is 0 before reject
    async with session_factory() as session:
        before_reject_count = await session.scalar(select(func.count()).select_from(Escalation))
    assert before_reject_count == 0

    decision = await client.post(
        f"/api/v1/threads/{thread_id}/decisions",
        headers=_auth(),
        json={"action_id": approval["data"]["action_id"], "decision": "reject"},
    )

    async with session_factory() as session:
        escalation_count = await session.scalar(select(func.count()).select_from(Escalation))

    assert decision.status_code == 200
    assert decision.json()["type"] == "action.rejected"
    assert escalation_count == 0


async def test_reauthorization_denies_mutation_if_permission_revoked(
    client: AsyncClient, session_factory
) -> None:
    """Prove that if permissions are revoked between proposal and approval, mutation is DENIED."""
    from app.schemas.auth import UserContext

    northstar = UserContext(
        user_id="USR-NORTHSTAR-1",
        role="customer",
        account_id="ACCT-001",
        permissions=frozenset({"orders:read", "tickets:read", "escalations:create"}),
    )
    thread_id = "thr-revoke"

    # Step 1: Proposal created while permission exists
    action_id = await _propose_escalation(session_factory, thread_id, northstar)

    # Step 2: Verify DB count is 0
    async with session_factory() as session:
        count_before = await session.scalar(select(func.count()).select_from(Escalation))
    assert count_before == 0

    # Step 3: Approval is attempted with a token where escalations:create has been REVOKED
    decision = await client.post(
        f"/api/v1/threads/{thread_id}/decisions",
        headers=_auth("mock-northstar-revoked"),
        json={"action_id": action_id, "decision": "approve"},
    )

    # Step 4: Endpoint must deny the mutation (403 Forbidden)
    assert decision.status_code == 403

    # Step 5: Database count must remain exactly 0
    async with session_factory() as session:
        count_after = await session.scalar(select(func.count()).select_from(Escalation))
    assert count_after == 0


async def test_decision_blocks_cross_tenant_approval_attempt(
    client: AsyncClient, session_factory
) -> None:
    """Prove that another tenant cannot approve a pending action belonging to Northstar."""
    from app.schemas.auth import UserContext

    northstar = UserContext(
        user_id="USR-NORTHSTAR-1",
        role="customer",
        account_id="ACCT-001",
        permissions=frozenset({"orders:read", "tickets:read", "escalations:create"}),
    )
    thread_id = "thr-tenant-isolation"

    action_id = await _propose_escalation(session_factory, thread_id, northstar)

    # Lumenworks attempts to approve Northstar's action
    decision = await client.post(
        f"/api/v1/threads/{thread_id}/decisions",
        headers=_auth("mock-lumenworks"),
        json={"action_id": action_id, "decision": "approve"},
    )

    # Must be 404 (thread not accessible to lumenworks) or 403
    assert decision.status_code in {403, 404}

    async with session_factory() as session:
        count = await session.scalar(select(func.count()).select_from(Escalation))
    assert count == 0


async def test_thread_ownership_blocks_other_customer(client: AsyncClient) -> None:
    await client.post(
        "/api/v1/chat/stream",
        headers=_auth("mock-northstar"),
        json={"thread_id": "thr-private", "message": "Can I cancel ORD-1001 without a fee?"},
    )

    owner = await client.get("/api/v1/threads/thr-private", headers=_auth("mock-northstar"))
    other = await client.get("/api/v1/threads/thr-private", headers=_auth("mock-lumenworks"))

    assert owner.status_code == 200
    assert other.status_code == 404
