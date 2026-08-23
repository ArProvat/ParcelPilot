"""Import validated workbook data into the operational database."""
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.ingestion.workbook_loader import load_workbook_data
from app.models import Account, DatasetConfig, Order, Ticket
from app.schemas.workbook import WorkbookData


def _account_from_import(account) -> Account:
    return Account(
        id=account.account_id,
        name=account.account_name,
        plan=account.plan,
        status=account.status,
        csm=account.csm,
        contract_file=account.contract_file,
        premium_support=account.premium_support,
        notes=account.notes,
    )


def _order_from_import(order) -> Order:
    return Order(
        id=order.order_id,
        account_id=order.account_id,
        carrier=order.carrier,
        status=order.status,
        booked_at=order.booked_at,
        pickup_window_start=order.pickup_window_start,
        pickup_window_end=order.pickup_window_end,
        pickup_actual_at=order.pickup_actual_at,
        shipment_fee_inr=order.shipment_fee_inr,
        carrier_fault=order.carrier_fault,
        customer_fault=order.customer_fault,
        cancellation_requested_at=order.cancellation_requested_at,
        notes=order.notes,
    )


def _ticket_from_import(ticket) -> Ticket:
    return Ticket(
        id=ticket.ticket_id,
        account_id=ticket.account_id,
        created_at=ticket.created_at,
        status=ticket.status,
        subject=ticket.subject,
        description=ticket.description,
        channel=ticket.channel,
        assigned_to=ticket.assigned_to,
        last_customer_message_at=ticket.last_customer_message_at,
        historical_resolution=ticket.historical_resolution,
    )


async def import_workbook_data(session: AsyncSession, data: WorkbookData) -> None:
    """Idempotently upsert validated workbook data into the database."""
    await session.merge(
        DatasetConfig(
            id=1,
            snapshot_at=data.metadata.snapshot_at,
            currency=data.metadata.currency,
            notes=data.metadata.notes,
            important_note=data.metadata.important_note,
        )
    )

    for account in data.accounts:
        await session.merge(_account_from_import(account))

    for order in data.orders:
        await session.merge(_order_from_import(order))

    for ticket in data.tickets:
        await session.merge(_ticket_from_import(ticket))


async def import_workbook_path(path: str | Path, session: AsyncSession | None = None) -> WorkbookData:
    """Load a workbook file and import it. Returns the validated domain data."""
    data = load_workbook_data(path)
    if session is not None:
        await import_workbook_data(session, data)
        return data

    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as new_session:
        async with new_session.begin():
            await import_workbook_data(new_session, data)
    return data


async def _main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Import ParcelPilot workbook data into PostgreSQL.")
    parser.add_argument(
        "path",
        nargs="?",
        default=str(Path(__file__).resolve().parents[3] / "data" / "ParcelPilot_Assessment_Data.xlsx"),
    )
    args = parser.parse_args()

    data = await import_workbook_path(args.path)
    print(
        f"Imported {len(data.accounts)} accounts, {len(data.orders)} orders, "
        f"{len(data.tickets)} tickets at snapshot {data.metadata.snapshot_at.isoformat()}."
    )


if __name__ == "__main__":
    import asyncio

    asyncio.run(_main())
