"""Tests for Phase 2 SQLAlchemy persistence and repository boundaries."""
from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.ingestion import IST, load_workbook_data
from app.ingestion.workbook import import_workbook_data
from app.models import Account, Order, Ticket
from app.repositories import OrderRepository, TicketRepository


@pytest.fixture
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_foreign_keys(dbapi_connection, connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as db_session:
        yield db_session

    await engine.dispose()


@pytest.fixture
def workbook_path():
    from pathlib import Path

    return Path(__file__).resolve().parents[2] / "data" / "ParcelPilot_Assessment_Data.xlsx"


async def test_order_belongs_to_account(session: AsyncSession, workbook_path) -> None:
    data = load_workbook_data(workbook_path)
    async with session.begin():
        await import_workbook_data(session, data)

    order = await OrderRepository(session).get_for_account(
        order_id="ORD-1001",
        account_id="ACCT-001",
    )

    assert order is not None
    assert order.id == "ORD-1001"
    assert order.account_id == "ACCT-001"


async def test_cross_account_order_hidden(session: AsyncSession, workbook_path) -> None:
    data = load_workbook_data(workbook_path)
    async with session.begin():
        await import_workbook_data(session, data)

    order = await OrderRepository(session).get_for_account(
        order_id="ORD-2001",
        account_id="ACCT-001",
    )

    assert order is None


async def test_ticket_foreign_key(session: AsyncSession) -> None:
    ticket = Ticket(
        id="TKT-BAD",
        account_id="ACCT-MISSING",
        created_at=datetime(2026, 8, 16, 11, 0, tzinfo=IST),
        status="open",
        subject="Missing account",
        description="Should violate FK.",
        channel="email",
    )

    session.add(ticket)
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_duplicate_import_is_safe(session: AsyncSession, workbook_path) -> None:
    data = load_workbook_data(workbook_path)

    async with session.begin():
        await import_workbook_data(session, data)

    async with session.begin():
        await import_workbook_data(session, data)

    account_count = await session.scalar(select(func.count()).select_from(Account))
    order_count = await session.scalar(select(func.count()).select_from(Order))
    ticket_count = await session.scalar(select(func.count()).select_from(Ticket))

    assert account_count == len(data.accounts)
    assert order_count == len(data.orders)
    assert ticket_count == len(data.tickets)


async def test_money_precision(session: AsyncSession, workbook_path) -> None:
    data = load_workbook_data(workbook_path)
    async with session.begin():
        await import_workbook_data(session, data)

    order = await OrderRepository(session).get_for_account("ORD-1001", "ACCT-001")

    assert order is not None
    assert isinstance(order.shipment_fee_inr, Decimal)
    assert order.shipment_fee_inr == Decimal("4200.00")


async def test_ticket_scoped_lookup(session: AsyncSession, workbook_path) -> None:
    data = load_workbook_data(workbook_path)
    async with session.begin():
        await import_workbook_data(session, data)

    ticket_repo = TicketRepository(session)

    assert await ticket_repo.get_for_account("TKT-501", "ACCT-001") is not None
    assert await ticket_repo.get_for_account("TKT-501", "ACCT-002") is None
