"""Tests for state-changing escalation actions with approval and audit."""
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.agent import create_parcelpilot_agent
from app.db.base import Base
from app.ingestion import load_workbook_data
from app.ingestion.workbook import import_workbook_data
from app.models import AuditEvent, Escalation
from app.schemas.auth import UserContext
from app.schemas.tools import CreateEscalationInput
from app.services.escalations import EscalationService
from app.tools import create_agent_tools
from tests.test_phase7_langchain_tools import BindableFakeChatModel


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
    data = load_workbook_data(Path(__file__).resolve().parents[2] / "data" / "ParcelPilot_Assessment_Data.xlsx")
    async with factory() as session:
        async with session.begin():
            await import_workbook_data(session, data)

    yield factory
    await engine.dispose()


def northstar_user(*permissions: str) -> UserContext:
    return UserContext(
        user_id="USR-NORTHSTAR-1",
        role="customer",
        account_id="ACCT-001",
        permissions=frozenset(permissions),
    )


def escalation_request() -> CreateEscalationInput:
    return CreateEscalationInput(
        ticket_id="TKT-501",
        priority="urgent",
        reason="P1 shipment creation outage with breached first-response SLA.",
    )


async def test_create_escalation_proposal_does_not_insert(session_factory) -> None:
    action_id = uuid4()
    async with session_factory() as session:
        async with session.begin():
            result = await EscalationService(session).propose_create_escalation(
                request=escalation_request(),
                user=northstar_user("tickets:read", "escalations:create"),
                thread_id="thr-123",
                action_id=action_id,
            )
        escalation_count = await session.scalar(select(func.count()).select_from(Escalation))
        audit_types = list(
            (
                await session.execute(select(AuditEvent.event_type).order_by(AuditEvent.created_at))
            ).scalars()
        )

    assert result.success is True
    assert result.type == "approval_required"
    assert result.action_id == action_id
    assert result.action.tool == "create_escalation"
    assert escalation_count == 0
    assert audit_types == ["ESCALATION_PROPOSED"]


async def test_approve_creates_escalation_and_audit_events(session_factory) -> None:
    action_id = uuid4()
    async with session_factory() as session:
        async with session.begin():
            service = EscalationService(session)
            await service.propose_create_escalation(
                request=escalation_request(),
                user=northstar_user("tickets:read", "escalations:create"),
                thread_id="thr-123",
                action_id=action_id,
            )
            result = await service.approve_action(
                action_id=action_id,
                user=northstar_user("tickets:read", "escalations:create"),
            )
        escalation = (await session.execute(select(Escalation))).scalar_one()
        audit_types = list(
            (
                await session.execute(select(AuditEvent.event_type).order_by(AuditEvent.created_at))
            ).scalars()
        )

    assert result.success is True
    assert result.type == "executed"
    assert result.escalation is not None
    assert result.escalation.created is True
    assert escalation.ticket_id == "TKT-501"
    assert escalation.account_id == "ACCT-001"
    assert escalation.idempotency_key == str(action_id)
    assert audit_types == ["ESCALATION_PROPOSED", "ESCALATION_APPROVED", "ESCALATION_CREATED"]


async def test_reject_does_not_create_escalation(session_factory) -> None:
    action_id = uuid4()
    async with session_factory() as session:
        async with session.begin():
            service = EscalationService(session)
            await service.propose_create_escalation(
                request=escalation_request(),
                user=northstar_user("tickets:read", "escalations:create"),
                thread_id="thr-123",
                action_id=action_id,
            )
            result = await service.reject_action(
                action_id=action_id,
                user=northstar_user("tickets:read", "escalations:create"),
            )
        escalation_count = await session.scalar(select(func.count()).select_from(Escalation))
        audit_types = list(
            (
                await session.execute(select(AuditEvent.event_type).order_by(AuditEvent.created_at))
            ).scalars()
        )

    assert result.success is True
    assert result.type == "rejected"
    assert result.message == "The escalation was not created."
    assert escalation_count == 0
    assert audit_types == ["ESCALATION_PROPOSED", "ESCALATION_REJECTED"]


async def test_double_approve_is_idempotent(session_factory) -> None:
    action_id = uuid4()
    async with session_factory() as session:
        async with session.begin():
            service = EscalationService(session)
            await service.propose_create_escalation(
                request=escalation_request(),
                user=northstar_user("tickets:read", "escalations:create"),
                thread_id="thr-123",
                action_id=action_id,
            )
            first = await service.approve_action(
                action_id=action_id,
                user=northstar_user("tickets:read", "escalations:create"),
            )
            second = await service.approve_action(
                action_id=action_id,
                user=northstar_user("tickets:read", "escalations:create"),
            )
        escalation_count = await session.scalar(select(func.count()).select_from(Escalation))

    assert first.success is True
    assert second.success is True
    assert escalation_count == 1
    assert first.escalation is not None
    assert second.escalation is not None
    assert first.escalation.escalation_id == second.escalation.escalation_id


async def test_resume_reauthorizes_before_mutation(session_factory) -> None:
    action_id = uuid4()
    async with session_factory() as session:
        async with session.begin():
            service = EscalationService(session)
            await service.propose_create_escalation(
                request=escalation_request(),
                user=northstar_user("tickets:read", "escalations:create"),
                thread_id="thr-123",
                action_id=action_id,
            )
            result = await service.approve_action(
                action_id=action_id,
                user=northstar_user("tickets:read"),
            )
        escalation_count = await session.scalar(select(func.count()).select_from(Escalation))

    assert result.success is False
    assert result.error is not None
    assert result.error.code == "FORBIDDEN"
    assert escalation_count == 0


async def test_create_escalation_tool_is_registered_as_write_tool(session_factory) -> None:
    tools = {tool.name: tool for tool in create_agent_tools(session_factory=session_factory)}

    assert "create_escalation" in tools
    assert set(tools["create_escalation"].args_schema.model_fields) == {"ticket_id", "priority", "reason"}
    assert "state-changing action" in tools["create_escalation"].description


def test_agent_factory_configures_human_approval_middleware(session_factory) -> None:
    tools = create_agent_tools(session_factory=session_factory)
    agent = create_parcelpilot_agent(
        model=BindableFakeChatModel(responses=["Done"]),
        tools=tools,
        checkpointer=None,
    )

    assert agent is not None
