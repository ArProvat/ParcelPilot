"""Unit tests for Phase 1 - Excel Workbook Ingestion and Domain Validation."""
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
import pytest
from pydantic import ValidationError

from app.ingestion import (
    IST,
    IngestionError,
    RelationalIntegrityError,
    WorkbookStructureError,
    load_workbook_data,
    parse_and_localize_datetime,
)
from app.schemas.workbook import (
    AccountImport,
    DatasetMetadata,
    OrderImport,
    TicketImport,
    WorkbookData,
)


@pytest.fixture
def workbook_path() -> Path:
    """Path to the assessment Excel data file."""
    # Find relative to workspace root or backend root
    base = Path(__file__).resolve().parent.parent.parent
    path = base / "data" / "ParcelPilot_Assessment_Data.xlsx"
    if not path.exists():
        path = Path("data/ParcelPilot_Assessment_Data.xlsx")
    return path


def test_load_real_assessment_workbook(workbook_path: Path):
    """Test loading the real assessment dataset."""
    assert workbook_path.exists(), f"File does not exist: {workbook_path}"
    data = load_workbook_data(workbook_path)

    # 1. Verify Metadata
    assert data.metadata is not None
    assert data.metadata.currency == "INR"
    assert data.metadata.snapshot_at.year == 2026
    assert data.metadata.snapshot_at.month == 8
    assert data.metadata.snapshot_at.day == 16
    assert data.metadata.snapshot_at.hour == 11
    assert data.metadata.snapshot_at.minute == 0
    assert data.metadata.snapshot_at.tzinfo is not None

    # 2. Verify Accounts
    assert len(data.accounts) == 4
    acct_map = {acc.account_id: acc for acc in data.accounts}
    assert "ACCT-001" in acct_map
    assert "ACCT-002" in acct_map
    assert "ACCT-003" in acct_map
    assert "ACCT-004" in acct_map

    northstar = acct_map["ACCT-001"]
    assert northstar.account_name == "Northstar Logistics"
    assert northstar.plan == "Enterprise"
    assert northstar.status == "active"
    assert northstar.csm == "Priya Mehta"
    assert northstar.premium_support is True
    assert northstar.contract_file == "05_Northstar_Logistics_Enterprise_Agreement.pdf"

    # 3. Verify Orders
    assert len(data.orders) == 6
    order_map = {o.order_id: o for o in data.orders}
    assert "ORD-1001" in order_map
    assert "ORD-2002" in order_map

    ord_1001 = order_map["ORD-1001"]
    assert ord_1001.account_id == "ACCT-001"
    assert ord_1001.carrier == "SwiftShip"
    assert ord_1001.status == "BOOKED"
    assert isinstance(ord_1001.shipment_fee_inr, Decimal)
    assert ord_1001.shipment_fee_inr == Decimal("4200.0")
    assert ord_1001.carrier_fault is False
    assert ord_1001.customer_fault is False
    assert ord_1001.cancellation_requested_at is not None
    assert ord_1001.cancellation_requested_at.tzinfo is not None

    # Verify carrier fault order
    ord_2002 = order_map["ORD-2002"]
    assert ord_2002.carrier_fault is True
    assert ord_2002.status == "BOOKED"

    # 4. Verify Tickets
    assert len(data.tickets) == 7
    ticket_map = {t.ticket_id: t for t in data.tickets}
    assert "TKT-501" in ticket_map
    assert "TKT-450" in ticket_map

    tkt_501 = ticket_map["TKT-501"]
    assert tkt_501.account_id == "ACCT-001"
    assert tkt_501.status == "open"
    assert tkt_501.channel == "email"
    assert tkt_501.historical_resolution is None

    tkt_450 = ticket_map["TKT-450"]
    assert tkt_450.account_id == "ACCT-001"
    assert tkt_450.status == "closed"
    assert tkt_450.historical_resolution is not None
    assert "INR 250" in tkt_450.historical_resolution


def test_snapshot_relative_delay_calculation(workbook_path: Path):
    """Test calculating operational delay relative to snapshot_at instead of datetime.now()."""
    data = load_workbook_data(workbook_path)
    snapshot = data.metadata.snapshot_at

    ord_2002 = data.get_order("ORD-2002")
    assert ord_2002 is not None

    # pickup_window_end was 2026-08-16 06:30 IST, snapshot is 2026-08-16 11:00 IST
    # Delay should be exactly 4.5 hours (270 minutes / 16200 seconds)
    delay: timedelta = snapshot - ord_2002.pickup_window_end
    assert delay == timedelta(hours=4, minutes=30)
    assert delay.total_seconds() == 16200


def test_decimal_monetary_precision(workbook_path: Path):
    """Verify that monetary fields are strictly parsed as Decimal and support exact addition."""
    data = load_workbook_data(workbook_path)
    fees = [order.shipment_fee_inr for order in data.orders]
    for fee in fees:
        assert isinstance(fee, Decimal)

    total_fees = sum(fees, Decimal("0.0"))
    # 4200.0 + 5100.0 + 1800.0 + 2400.0 + 1200.0 + 3600.0 = 18300.0
    assert total_fees == Decimal("18300.0")


def test_helper_lookup_methods(workbook_path: Path):
    """Test helper lookup methods on WorkbookData."""
    data = load_workbook_data(workbook_path)

    # get_account
    assert data.get_account("ACCT-001") is not None
    assert data.get_account("ACCT-NONEXISTENT") is None

    # get_orders_for_account
    acct1_orders = data.get_orders_for_account("ACCT-001")
    assert len(acct1_orders) == 2
    assert {o.order_id for o in acct1_orders} == {"ORD-1001", "ORD-1002"}

    # get_tickets_for_account
    acct1_tickets = data.get_tickets_for_account("ACCT-001")
    assert len(acct1_tickets) == 3
    assert {t.ticket_id for t in acct1_tickets} == {"TKT-501", "TKT-504", "TKT-450"}


def test_relational_integrity_unknown_account_in_order():
    """Verify that an order with a non-existent account_id raises RelationalIntegrityError."""
    metadata = DatasetMetadata(snapshot_at=datetime(2026, 8, 16, 11, 0, tzinfo=IST), currency="INR")
    account = AccountImport(account_id="ACCT-001", account_name="Test", plan="Standard", status="active")
    order = OrderImport(
        order_id="ORD-9999",
        account_id="ACCT-UNKNOWN",
        carrier="SwiftShip",
        status="BOOKED",
        booked_at=datetime(2026, 8, 16, 9, 0, tzinfo=IST),
        pickup_window_start=datetime(2026, 8, 16, 10, 0, tzinfo=IST),
        pickup_window_end=datetime(2026, 8, 16, 11, 0, tzinfo=IST),
        shipment_fee_inr=Decimal("500"),
    )

    with pytest.raises((ValueError, RelationalIntegrityError)) as exc_info:
        WorkbookData(metadata=metadata, accounts=[account], orders=[order], tickets=[])
    assert "unknown account_id 'ACCT-UNKNOWN'" in str(exc_info.value)


def test_relational_integrity_unknown_account_in_ticket():
    """Verify that a ticket with a non-existent account_id raises RelationalIntegrityError."""
    metadata = DatasetMetadata(snapshot_at=datetime(2026, 8, 16, 11, 0, tzinfo=IST), currency="INR")
    account = AccountImport(account_id="ACCT-001", account_name="Test", plan="Standard", status="active")
    ticket = TicketImport(
        ticket_id="TKT-999",
        account_id="ACCT-GHOST",
        created_at=datetime(2026, 8, 16, 10, 0, tzinfo=IST),
        status="open",
        subject="Broken",
        description="Help",
        channel="email",
    )

    with pytest.raises((ValueError, RelationalIntegrityError)) as exc_info:
        WorkbookData(metadata=metadata, accounts=[account], orders=[], tickets=[ticket])
    assert "unknown account_id 'ACCT-GHOST'" in str(exc_info.value)


def test_order_business_invariants():
    """Test validation of order business invariants."""
    # 1. Invalid pickup window (start > end)
    with pytest.raises(ValidationError):
        OrderImport(
            order_id="ORD-ERR-1",
            account_id="ACCT-001",
            carrier="SwiftShip",
            status="BOOKED",
            booked_at=datetime(2026, 8, 16, 9, 0, tzinfo=IST),
            pickup_window_start=datetime(2026, 8, 16, 12, 0, tzinfo=IST),
            pickup_window_end=datetime(2026, 8, 16, 10, 0, tzinfo=IST),  # Before start
            shipment_fee_inr=Decimal("100"),
        )

    # 2. Negative fee
    with pytest.raises(ValidationError):
        OrderImport(
            order_id="ORD-ERR-2",
            account_id="ACCT-001",
            carrier="SwiftShip",
            status="BOOKED",
            booked_at=datetime(2026, 8, 16, 9, 0, tzinfo=IST),
            pickup_window_start=datetime(2026, 8, 16, 10, 0, tzinfo=IST),
            pickup_window_end=datetime(2026, 8, 16, 11, 0, tzinfo=IST),
            shipment_fee_inr=Decimal("-50"),
        )

    # 3. Pickup actual before booked_at
    with pytest.raises(ValidationError):
        OrderImport(
            order_id="ORD-ERR-3",
            account_id="ACCT-001",
            carrier="SwiftShip",
            status="PICKED_UP",
            booked_at=datetime(2026, 8, 16, 10, 0, tzinfo=IST),
            pickup_window_start=datetime(2026, 8, 16, 10, 30, tzinfo=IST),
            pickup_window_end=datetime(2026, 8, 16, 11, 30, tzinfo=IST),
            pickup_actual_at=datetime(2026, 8, 16, 9, 0, tzinfo=IST),  # Before booking!
            shipment_fee_inr=Decimal("100"),
        )


def test_file_not_found():
    """Test error raised when workbook file does not exist."""
    with pytest.raises(FileNotFoundError):
        load_workbook_data("non_existent_file.xlsx")


def test_parse_and_localize_datetime():
    """Test datetime parser and timezone localizer."""
    # String with explicit timezone text
    dt1 = parse_and_localize_datetime("2026-08-16 11:00 Asia/Kolkata")
    assert dt1 is not None
    assert dt1.tzinfo is not None
    assert dt1.hour == 11

    # Naive string gets IST
    dt2 = parse_and_localize_datetime("2026-08-16 09:30")
    assert dt2 is not None
    assert dt2.tzinfo is not None
    assert dt2.hour == 9
    assert dt2.minute == 30

    # None returns None
    assert parse_and_localize_datetime(None) is None
    assert parse_and_localize_datetime("") is None
