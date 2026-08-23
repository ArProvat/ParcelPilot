"""Tests for FastAPI chat streaming and approval protocol."""
from pathlib import Path
import json

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.dependency import get_db_session
from app.ingestion import load_workbook_data
from app.ingestion.workbook import import_workbook_data
from app.main import app
from app.models import Escalation
from app.retrieval import import_document_corpus


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


def _auth(token: str = "mock-northstar") -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _parse_sse(body: str) -> list[dict]:
    events = []
    for block in body.strip().split("\n\n"):
        data_line = next(line for line in block.splitlines() if line.startswith("data: "))
        events.append(json.loads(data_line.removeprefix("data: ")))
    return events


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
    event_types = [event["type"] for event in events]

    assert response.status_code == 200
    assert "message.started" in event_types
    assert "tool.started" in event_types
    assert "decision.completed" in event_types
    assert "source.retrieved" in event_types
    assert "message.completed" in event_types
    assert all("reasoning" not in event["type"] for event in events)


async def test_escalation_stream_requires_approval_then_decision_executes(client: AsyncClient, session_factory) -> None:
    response = await client.post(
        "/api/v1/chat/stream",
        headers=_auth(),
        json={"thread_id": "thr-escalate", "message": "Check TKT-501 and escalate it if needed."},
    )
    events = _parse_sse(response.text)
    approval = next(event for event in events if event["type"] == "approval.required")
    action_id = approval["data"]["action_id"]

    async with session_factory() as session:
        before_count = await session.scalar(select(func.count()).select_from(Escalation))

    decision = await client.post(
        "/api/v1/threads/thr-escalate/decisions",
        headers=_auth(),
        json={"action_id": action_id, "decision": "approve"},
    )

    async with session_factory() as session:
        after_count = await session.scalar(select(func.count()).select_from(Escalation))

    assert before_count == 0
    assert decision.status_code == 200
    assert decision.json()["type"] == "action.completed"
    assert after_count == 1


async def test_decision_reject_does_not_create_escalation(client: AsyncClient, session_factory) -> None:
    response = await client.post(
        "/api/v1/chat/stream",
        headers=_auth(),
        json={"thread_id": "thr-reject", "message": "Check TKT-501 and escalate it if needed."},
    )
    approval = next(event for event in _parse_sse(response.text) if event["type"] == "approval.required")

    decision = await client.post(
        "/api/v1/threads/thr-reject/decisions",
        headers=_auth(),
        json={"action_id": approval["data"]["action_id"], "decision": "reject"},
    )

    async with session_factory() as session:
        escalation_count = await session.scalar(select(func.count()).select_from(Escalation))

    assert decision.status_code == 200
    assert decision.json()["type"] == "action.rejected"
    assert escalation_count == 0


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
