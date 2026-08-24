"""Phase 1 Formal Invariant Tests — State durability, Idempotency, and Security Context."""
from pathlib import Path
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.agent.stream_events import AgentEventTranslator
from app.db.base import Base
from app.dependency import get_db_session
from app.ingestion import load_workbook_data
from app.ingestion.workbook import import_workbook_data
from app.main import app
from app.models import AuditEvent, Escalation
from app.retrieval import import_document_corpus
from app.schemas.auth import UserContext
from app.schemas.tools import CreateEscalationInput
from app.services.agent_stream import AgentStreamService
from app.services.escalations import EscalationService


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


@pytest.fixture
async def client(session_factory):
    async def override_session():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as test_client:
        yield test_client

    app.dependency_overrides.clear()
    if hasattr(app.state, "agent_stream_service"):
        del app.state.agent_stream_service


def _auth(token: str = "mock-northstar") -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def northstar_user(*permissions: str) -> UserContext:
    perms = permissions or ("orders:read", "tickets:read", "escalations:create")
    return UserContext(
        user_id="USR-NORTHSTAR-1",
        role="customer",
        account_id="ACCT-001",
        permissions=frozenset(perms),
    )


async def _propose_escalation(session_factory, thread_id: str, user: UserContext) -> str:
    from app.repositories import ConversationThreadRepository

    action_id = uuid4()
    async with session_factory() as session:
        async with session.begin():
            await ConversationThreadRepository(session).ensure_access(thread_id, user)
            result = await EscalationService(session).propose_create_escalation(
                request=CreateEscalationInput(
                    ticket_id="TKT-501",
                    priority="urgent",
                    reason="P1 shipment creation outage with breached SLA.",
                ),
                user=user,
                thread_id=thread_id,
                action_id=action_id,
            )
    return str(result.action_id)


# ---------------------------------------------------------------------------
# Invariant 1: Approval Before Mutation
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_invariant_approval_before_mutation(client: AsyncClient, session_factory):
    """Initial count 0 -> interrupt count 0 -> approval count 1."""
    thread_id = "thr-inv-approval"
    user = northstar_user()

    # 1. Before proposal / interrupt: count == 0
    async with session_factory() as session:
        count_0 = await session.scalar(select(func.count()).select_from(Escalation))
    assert count_0 == 0

    # 2. Proposal / Interrupt created: count MUST remain 0
    action_id = await _propose_escalation(session_factory, thread_id, user)
    async with session_factory() as session:
        count_after_proposal = await session.scalar(select(func.count()).select_from(Escalation))
    assert count_after_proposal == 0

    # 3. Explicit Approval submitted: count MUST become 1
    resp = await client.post(
        f"/api/v1/threads/{thread_id}/decisions",
        headers=_auth("mock-northstar"),
        json={"action_id": action_id, "decision": "approve"},
    )
    assert resp.status_code == 200
    assert resp.json()["type"] == "action.completed"

    async with session_factory() as session:
        count_after_approval = await session.scalar(select(func.count()).select_from(Escalation))
    assert count_after_approval == 1


# ---------------------------------------------------------------------------
# Invariant 2: Permission Revoked Before Resume
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_invariant_permission_revoked_before_resume(client: AsyncClient, session_factory):
    """Proposal allowed with permissions; if permissions revoked, approval must fail with 403 and count remains 0."""
    thread_id = "thr-inv-revoke"
    user = northstar_user()

    action_id = await _propose_escalation(session_factory, thread_id, user)

    # User attempts approval with a token lacking escalations:create
    resp = await client.post(
        f"/api/v1/threads/{thread_id}/decisions",
        headers=_auth("mock-northstar-revoked"),
        json={"action_id": action_id, "decision": "approve"},
    )
    assert resp.status_code == 403

    async with session_factory() as session:
        count = await session.scalar(select(func.count()).select_from(Escalation))
    assert count == 0


# ---------------------------------------------------------------------------
# Invariant 3: Cross-Tenant Approval Attempt Denied
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_invariant_cross_tenant_approval_denied(client: AsyncClient, session_factory):
    """LumenWorks cannot approve Northstar's pending action; count remains 0."""
    thread_id = "thr-inv-cross-tenant"
    user = northstar_user()

    action_id = await _propose_escalation(session_factory, thread_id, user)

    resp = await client.post(
        f"/api/v1/threads/{thread_id}/decisions",
        headers=_auth("mock-lumenworks"),
        json={"action_id": action_id, "decision": "approve"},
    )
    assert resp.status_code in {403, 404}

    async with session_factory() as session:
        count = await session.scalar(select(func.count()).select_from(Escalation))
    assert count == 0


# ---------------------------------------------------------------------------
# Invariant 4: Duplicate Approval Idempotency
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_invariant_duplicate_approval_is_idempotent(client: AsyncClient, session_factory):
    """Approve once -> count 1. Approve same action_id again -> returns 200, count remains 1, exact audit trail."""
    thread_id = "thr-inv-dup-approve"
    user = northstar_user()

    action_id = await _propose_escalation(session_factory, thread_id, user)

    # First approval
    resp1 = await client.post(
        f"/api/v1/threads/{thread_id}/decisions",
        headers=_auth("mock-northstar"),
        json={"action_id": action_id, "decision": "approve"},
    )
    assert resp1.status_code == 200
    assert resp1.json()["type"] == "action.completed"

    # Second approval on the exact same action_id
    resp2 = await client.post(
        f"/api/v1/threads/{thread_id}/decisions",
        headers=_auth("mock-northstar"),
        json={"action_id": action_id, "decision": "approve"},
    )
    assert resp2.status_code == 200
    assert resp2.json()["type"] == "action.completed"

    # Verify count is strictly 1
    async with session_factory() as session:
        count = await session.scalar(select(func.count()).select_from(Escalation))
        audit_events = list(
            (
                await session.execute(
                    select(AuditEvent.event_type)
                    .where(AuditEvent.thread_id == thread_id)
                    .order_by(AuditEvent.created_at)
                )
            ).scalars()
        )

    assert count == 1
    # Exactly one proposed, approved, created audit event
    assert audit_events == ["ESCALATION_PROPOSED", "ESCALATION_APPROVED", "ESCALATION_CREATED"]


# ---------------------------------------------------------------------------
# Invariant 5: Duplicate Rejection Idempotency
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_invariant_duplicate_rejection_is_idempotent(client: AsyncClient, session_factory):
    """Reject once -> count 0. Reject same action_id again -> returns 200, count remains 0, exact audit trail."""
    thread_id = "thr-inv-dup-reject"
    user = northstar_user()

    action_id = await _propose_escalation(session_factory, thread_id, user)

    # First reject
    resp1 = await client.post(
        f"/api/v1/threads/{thread_id}/decisions",
        headers=_auth("mock-northstar"),
        json={"action_id": action_id, "decision": "reject"},
    )
    assert resp1.status_code == 200
    assert resp1.json()["type"] == "action.rejected"

    # Second reject
    resp2 = await client.post(
        f"/api/v1/threads/{thread_id}/decisions",
        headers=_auth("mock-northstar"),
        json={"action_id": action_id, "decision": "reject"},
    )
    assert resp2.status_code == 200
    assert resp2.json()["type"] == "action.rejected"

    # Verify count is strictly 0 and audit events are not duplicated
    async with session_factory() as session:
        count = await session.scalar(select(func.count()).select_from(Escalation))
        audit_events = list(
            (
                await session.execute(
                    select(AuditEvent.event_type)
                    .where(AuditEvent.thread_id == thread_id)
                    .order_by(AuditEvent.created_at)
                )
            ).scalars()
        )

    assert count == 0
    assert audit_events == ["ESCALATION_PROPOSED", "ESCALATION_REJECTED"]


# ---------------------------------------------------------------------------
# Invariant 6: Reject Then Approve Blocked
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_invariant_approve_after_reject_blocked(client: AsyncClient, session_factory):
    """Once rejected, an action cannot subsequently be approved."""
    thread_id = "thr-inv-rej-then-app"
    user = northstar_user()

    action_id = await _propose_escalation(session_factory, thread_id, user)

    # Reject
    resp1 = await client.post(
        f"/api/v1/threads/{thread_id}/decisions",
        headers=_auth("mock-northstar"),
        json={"action_id": action_id, "decision": "reject"},
    )
    assert resp1.status_code == 200
    assert resp1.json()["type"] == "action.rejected"

    # Attempt Approve
    resp2 = await client.post(
        f"/api/v1/threads/{thread_id}/decisions",
        headers=_auth("mock-northstar"),
        json={"action_id": action_id, "decision": "approve"},
    )
    assert resp2.json()["result"]["success"] is False

    async with session_factory() as session:
        count = await session.scalar(select(func.count()).select_from(Escalation))
    assert count == 0
