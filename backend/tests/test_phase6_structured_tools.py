"""Tests for authorized structured operational-data tools."""
from pathlib import Path

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.ingestion import load_workbook_data
from app.ingestion.workbook import import_workbook_data
from app.schemas.auth import UserContext
from app.services.operational_data import OperationalDataService
from app.tools import create_structured_data_tools


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
        permissions=frozenset({"accounts:read", "orders:read", "tickets:read"}),
    )


async def test_get_order_returns_minimum_operational_facts(session_factory) -> None:
    async with session_factory() as session:
        result = await OperationalDataService(session).get_visible_order("ORD-2002", northstar_user())

    assert result.success is False
    assert result.found is False
    assert result.error is not None
    assert result.error.code == "NOT_FOUND"


async def test_get_order_calculates_snapshot_relative_delay(session_factory) -> None:
    async with session_factory() as session:
        result = await OperationalDataService(session).get_visible_order("ORD-1001", northstar_user())

    assert result.success is True
    assert result.found is True
    assert result.order_id == "ORD-1001"
    assert result.pickup_delay_minutes == 0
    assert result.booking_age_minutes is not None
    assert result.shipment_fee_inr is not None
    assert result.model_dump().get("account_id") is None
    assert result.model_dump().get("notes") is None


async def test_get_ticket_marks_historical_resolution_context_only(session_factory) -> None:
    async with session_factory() as session:
        result = await OperationalDataService(session).get_visible_ticket("TKT-450", northstar_user())

    assert result.success is True
    assert result.found is True
    assert result.historical_resolution is not None
    assert result.historical_resolution_authority == "context_only"


async def test_get_my_account_does_not_allow_arbitrary_account_id(session_factory) -> None:
    async with session_factory() as session:
        result = await OperationalDataService(session).get_my_account(northstar_user())

    assert result.success is True
    assert result.found is True
    assert result.account_id == "ACCT-001"
    assert result.name == "Northstar Logistics"


async def test_list_account_tickets_uses_authenticated_scope(session_factory) -> None:
    async with session_factory() as session:
        result = await OperationalDataService(session).list_account_tickets("all", northstar_user())

    assert result.success is True
    assert {ticket.ticket_id for ticket in result.tickets} == {"TKT-501", "TKT-504", "TKT-450"}


async def test_langchain_get_order_tool_has_no_account_id_input(session_factory) -> None:
    tools = {tool.name: tool for tool in create_structured_data_tools(northstar_user(), session_factory=session_factory)}

    input_fields = set(tools["get_order"].args_schema.model_fields)
    result = await tools["get_order"].ainvoke({"order_id": "ORD-1001"})

    assert input_fields == {"order_id"}
    assert result["found"] is True
    assert result["order_id"] == "ORD-1001"
    assert "account_id" not in result


async def test_langchain_tool_hides_cross_account_order(session_factory) -> None:
    tools = {tool.name: tool for tool in create_structured_data_tools(northstar_user(), session_factory=session_factory)}

    result = await tools["get_order"].ainvoke({"order_id": "ORD-2001"})

    assert result["success"] is False
    assert result["found"] is False
    assert result["error"]["code"] == "NOT_FOUND"
