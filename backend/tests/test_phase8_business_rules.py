"""Tests for deterministic business rules and calculation tools."""
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.ingestion import load_workbook_data
from app.ingestion.workbook import import_workbook_data
from app.schemas.auth import UserContext
from app.services.business_rules import BusinessRuleService
from app.tools import create_agent_tools


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


def northstar_user() -> UserContext:
    return UserContext(
        user_id="USR-NORTHSTAR-1",
        role="customer",
        account_id="ACCT-001",
        permissions=frozenset({"orders:read", "tickets:read"}),
    )


def lumenworks_user() -> UserContext:
    return UserContext(
        user_id="USR-LUMENWORKS-1",
        role="customer",
        account_id="ACCT-002",
        permissions=frozenset({"orders:read", "tickets:read"}),
    )


async def test_ord_1001_cancellation_allowed_zero_fee(session_factory) -> None:
    async with session_factory() as session:
        decision = await BusinessRuleService(session).evaluate_cancellation("ORD-1001", northstar_user())

    assert decision.allowed is True
    assert decision.fee_inr == Decimal("0.00")
    assert decision.reason_code == "CONTRACT_WAIVER"
    assert "Northstar Logistics Enterprise Agreement" in decision.applied_sources


async def test_ord_2001_cancellation_allowed_standard_fee(session_factory) -> None:
    async with session_factory() as session:
        decision = await BusinessRuleService(session).evaluate_cancellation("ORD-2001", lumenworks_user())

    assert decision.allowed is True
    assert decision.fee_inr == Decimal("250.00")
    assert decision.reason_code == "BOOKED_STANDARD_FEE"


async def test_ord_2002_service_credit_uses_lumenworks_override(session_factory) -> None:
    async with session_factory() as session:
        decision = await BusinessRuleService(session).evaluate_service_credit("ORD-2002", lumenworks_user())

    assert decision.eligible is True
    assert decision.amount_inr == Decimal("300.00")
    assert decision.delay_minutes == 270
    assert decision.rule_source == "LumenWorks Service Agreement"
    assert decision.requires_verification is False


async def test_tkt_501_sla_breached_and_escalation_recommended(session_factory) -> None:
    async with session_factory() as session:
        decision = await BusinessRuleService(session).evaluate_ticket_sla("TKT-501", northstar_user())

    assert decision.severity == "P1"
    assert decision.response_target_minutes == 15
    assert decision.breached is True
    assert decision.breach_minutes == 15
    assert decision.requires_immediate_escalation is True
    assert decision.source == "Northstar Logistics Enterprise Agreement"


async def test_business_rule_tools_are_registered_and_deterministic(session_factory) -> None:
    tools = {tool.name: tool for tool in create_agent_tools(lumenworks_user(), session_factory=session_factory)}

    credit = await tools["evaluate_service_credit"].ainvoke({"order_id": "ORD-2002"})
    cancellation = await tools["evaluate_cancellation"].ainvoke({"order_id": "ORD-2001"})

    assert set(tools["evaluate_service_credit"].args_schema.model_fields) == {"order_id"}
    assert credit["eligible"] is True
    assert credit["amount_inr"] == "300.00"
    assert cancellation["allowed"] is True
    assert cancellation["fee_inr"] == "250.00"
