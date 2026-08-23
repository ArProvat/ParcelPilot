"""Pydantic schemas for workbook ingestion and domain validation."""
from datetime import datetime
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class DatasetMetadata(BaseModel):
    """Metadata extracted from the README sheet of the dataset."""
    model_config = ConfigDict(frozen=True)

    snapshot_at: datetime = Field(
        ...,
        description="Authoritative snapshot timestamp for all time-relative dataset calculations.",
    )
    currency: str = Field(
        default="INR",
        description="Currency code for all monetary fields in the dataset.",
    )
    notes: str | None = Field(
        default=None,
        description="General notes from the README sheet.",
    )
    important_note: str | None = Field(
        default=None,
        description="Special instructions or context (e.g. historical resolution authority).",
    )


class AccountImport(BaseModel):
    """Account domain record imported from Excel."""
    model_config = ConfigDict(frozen=True)

    account_id: str
    account_name: str
    plan: Literal["Standard", "Growth", "Enterprise"]
    status: Literal["active", "inactive"]
    csm: str | None = None
    contract_file: str | None = None
    premium_support: bool = False
    notes: str | None = None


class OrderImport(BaseModel):
    """Order domain record imported from Excel."""
    model_config = ConfigDict(frozen=True)

    order_id: str
    account_id: str
    carrier: str
    status: Literal["DRAFT", "BOOKED", "PICKED_UP", "DELIVERED"]
    booked_at: datetime
    pickup_window_start: datetime
    pickup_window_end: datetime
    pickup_actual_at: datetime | None = None
    shipment_fee_inr: Decimal
    carrier_fault: bool = False
    customer_fault: bool = False
    cancellation_requested_at: datetime | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def validate_order_invariants(self) -> "OrderImport":
        """Validate temporal and numeric business invariants for the order."""
        if self.shipment_fee_inr < Decimal("0"):
            raise ValueError(f"shipment_fee_inr cannot be negative: {self.shipment_fee_inr}")

        if self.pickup_window_start > self.pickup_window_end:
            raise ValueError(
                f"pickup_window_start ({self.pickup_window_start}) cannot be after "
                f"pickup_window_end ({self.pickup_window_end})"
            )

        if self.pickup_actual_at is not None and self.pickup_actual_at < self.booked_at:
            raise ValueError(
                f"pickup_actual_at ({self.pickup_actual_at}) cannot be before "
                f"booked_at ({self.booked_at})"
            )

        if self.cancellation_requested_at is not None and self.cancellation_requested_at < self.booked_at:
            raise ValueError(
                f"cancellation_requested_at ({self.cancellation_requested_at}) cannot be before "
                f"booked_at ({self.booked_at})"
            )

        return self


class TicketImport(BaseModel):
    """Support ticket domain record imported from Excel.
    
    Note on historical_resolution: Historical ticket resolutions may be inaccurate or
    inconsistent with active contract terms. They must be treated solely as historical
    context and not as authoritative policy.
    """
    model_config = ConfigDict(frozen=True)

    ticket_id: str
    account_id: str
    created_at: datetime
    status: Literal["open", "closed"]
    subject: str
    description: str
    channel: Literal["email", "chat"]
    assigned_to: str | None = None
    last_customer_message_at: datetime | None = None
    historical_resolution: str | None = None

    @model_validator(mode="after")
    def validate_ticket_invariants(self) -> "TicketImport":
        """Validate temporal invariants for the ticket."""
        if self.last_customer_message_at is not None and self.last_customer_message_at < self.created_at:
            raise ValueError(
                f"last_customer_message_at ({self.last_customer_message_at}) cannot be before "
                f"created_at ({self.created_at})"
            )
        return self


class WorkbookData(BaseModel):
    """Complete container for validated workbook domain data."""
    model_config = ConfigDict(frozen=True)

    metadata: DatasetMetadata
    accounts: list[AccountImport]
    orders: list[OrderImport]
    tickets: list[TicketImport]

    @model_validator(mode="after")
    def validate_relationships(self) -> "WorkbookData":
        """Validate cross-entity referential integrity and unique constraints."""
        # Uniqueness checks
        account_ids = set()
        for acc in self.accounts:
            if acc.account_id in account_ids:
                raise ValueError(f"Duplicate account_id detected: {acc.account_id}")
            account_ids.add(acc.account_id)

        order_ids = set()
        for ord_item in self.orders:
            if ord_item.order_id in order_ids:
                raise ValueError(f"Duplicate order_id detected: {ord_item.order_id}")
            order_ids.add(ord_item.order_id)

        ticket_ids = set()
        for tkt in self.tickets:
            if tkt.ticket_id in ticket_ids:
                raise ValueError(f"Duplicate ticket_id detected: {tkt.ticket_id}")
            ticket_ids.add(tkt.ticket_id)

        # Referential integrity checks
        for ord_item in self.orders:
            if ord_item.account_id not in account_ids:
                raise ValueError(
                    f"Referential integrity failure: Order {ord_item.order_id} references "
                    f"unknown account_id '{ord_item.account_id}'"
                )

        for tkt in self.tickets:
            if tkt.account_id not in account_ids:
                raise ValueError(
                    f"Referential integrity failure: Ticket {tkt.ticket_id} references "
                    f"unknown account_id '{tkt.account_id}'"
                )

        return self

    def get_account(self, account_id: str) -> AccountImport | None:
        """Lookup account by account_id."""
        for acc in self.accounts:
            if acc.account_id == account_id:
                return acc
        return None

    def get_orders_for_account(self, account_id: str) -> list[OrderImport]:
        """Get all orders associated with an account."""
        return [o for o in self.orders if o.account_id == account_id]

    def get_tickets_for_account(self, account_id: str) -> list[TicketImport]:
        """Get all tickets associated with an account."""
        return [t for t in self.tickets if t.account_id == account_id]

    def get_order(self, order_id: str) -> OrderImport | None:
        """Lookup order by order_id."""
        for o in self.orders:
            if o.order_id == order_id:
                return o
        return None

    def get_ticket(self, ticket_id: str) -> TicketImport | None:
        """Lookup ticket by ticket_id."""
        for t in self.tickets:
            if t.ticket_id == ticket_id:
                return t
        return None
