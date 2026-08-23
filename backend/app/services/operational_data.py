"""Services for authorized structured operational-data lookup."""
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import AccountRepository, DatasetConfigRepository, OrderRepository, TicketRepository
from app.schemas.auth import UserContext
from app.schemas.tools import (
    AccountToolResult,
    ListAccountTicketsResult,
    OrderToolResult,
    TicketSummary,
    TicketToolResult,
    ToolError,
)
from app.security.authorization import can_access_account, require_permission


class OperationalDataService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.accounts = AccountRepository(session)
        self.dataset_config = DatasetConfigRepository(session)
        self.orders = OrderRepository(session)
        self.tickets = TicketRepository(session)

    async def get_visible_order(self, order_id: str, user: UserContext) -> OrderToolResult:
        if not order_id.strip():
            return _order_not_found("No accessible order was found.")

        order = await self.orders.get_accessible(order_id.strip(), user)
        if order is None:
            return _order_not_found("No accessible order was found.")

        snapshot_at = await self.dataset_config.snapshot_time()
        return OrderToolResult(
            success=True,
            found=True,
            order_id=order.id,
            status=order.status,
            carrier=order.carrier,
            booked_at=order.booked_at,
            pickup_window_start=order.pickup_window_start,
            pickup_window_end=order.pickup_window_end,
            pickup_actual_at=order.pickup_actual_at,
            pickup_delay_minutes=pickup_delay_minutes(snapshot_at, order.pickup_window_end),
            booking_age_minutes=booking_age_minutes(snapshot_at, order.booked_at),
            shipment_fee_inr=order.shipment_fee_inr,
            carrier_fault=order.carrier_fault,
            customer_fault=order.customer_fault,
            cancellation_requested_at=order.cancellation_requested_at,
        )

    async def get_visible_ticket(self, ticket_id: str, user: UserContext) -> TicketToolResult:
        if not ticket_id.strip():
            return _ticket_not_found("No accessible ticket was found.")

        ticket = await self.tickets.get_accessible(ticket_id.strip(), user)
        if ticket is None:
            return _ticket_not_found("No accessible ticket was found.")

        return TicketToolResult(
            success=True,
            found=True,
            ticket_id=ticket.id,
            status=ticket.status,
            subject=ticket.subject,
            description=ticket.description,
            created_at=ticket.created_at,
            last_customer_message_at=ticket.last_customer_message_at,
            assigned_to=ticket.assigned_to,
            historical_resolution=ticket.historical_resolution,
            historical_resolution_authority="context_only" if ticket.historical_resolution else None,
        )

    async def get_my_account(self, user: UserContext) -> AccountToolResult:
        require_permission(user, "accounts:read")
        if user.account_id is None:
            return _account_not_found("No accessible account was found.")

        account = await self.accounts.get(user.account_id)
        if account is None:
            return _account_not_found("No accessible account was found.")

        return AccountToolResult(
            success=True,
            found=True,
            account_id=account.id,
            name=account.name,
            plan=account.plan,
            status=account.status,
            csm=account.csm,
            contract_file=account.contract_file,
            premium_support=account.premium_support,
        )

    async def get_account(self, account_id: str, user: UserContext) -> AccountToolResult:
        require_permission(user, "accounts:read")
        if not can_access_account(user, account_id):
            return _account_not_found("No accessible account was found.")

        account = await self.accounts.get(account_id)
        if account is None:
            return _account_not_found("No accessible account was found.")

        return AccountToolResult(
            success=True,
            found=True,
            account_id=account.id,
            name=account.name,
            plan=account.plan,
            status=account.status,
            csm=account.csm,
            contract_file=account.contract_file,
            premium_support=account.premium_support,
        )

    async def list_account_tickets(self, status: str, user: UserContext) -> ListAccountTicketsResult:
        require_permission(user, "tickets:read")
        if status == "open":
            tickets = await self.tickets.list_open_accessible(user)
        elif status == "closed":
            tickets = [ticket for ticket in await self.tickets.list_accessible(user) if ticket.status == "closed"]
        elif status == "all":
            tickets = await self.tickets.list_accessible(user)
        else:
            return ListAccountTicketsResult(
                success=False,
                tickets=[],
                error=ToolError(code="INVALID_ID", message="Ticket status must be open, closed, or all."),
            )

        return ListAccountTicketsResult(
            success=True,
            tickets=[
                TicketSummary(
                    ticket_id=ticket.id,
                    status=ticket.status,
                    subject=ticket.subject,
                    created_at=ticket.created_at,
                    last_customer_message_at=ticket.last_customer_message_at,
                    assigned_to=ticket.assigned_to,
                )
                for ticket in tickets
            ],
        )


def pickup_delay_minutes(snapshot_at: datetime, pickup_window_end: datetime) -> int:
    delta = snapshot_at - pickup_window_end
    return max(int(delta.total_seconds() / 60), 0)


def booking_age_minutes(snapshot_at: datetime, booked_at: datetime) -> int:
    delta = snapshot_at - booked_at
    return max(int(delta.total_seconds() / 60), 0)


def _order_not_found(message: str) -> OrderToolResult:
    return OrderToolResult(success=False, found=False, error=ToolError(code="NOT_FOUND", message=message))


def _ticket_not_found(message: str) -> TicketToolResult:
    return TicketToolResult(success=False, found=False, error=ToolError(code="NOT_FOUND", message=message))


def _account_not_found(message: str) -> AccountToolResult:
    return AccountToolResult(success=False, found=False, error=ToolError(code="NOT_FOUND", message=message))
