"""Typed result objects for structured-data tools."""
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict


class ToolError(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: Literal["NOT_FOUND", "FORBIDDEN", "INVALID_ID", "DATA_INCOMPLETE", "INTERNAL_ERROR"]
    message: str


class ToolResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    success: bool
    error: ToolError | None = None


class GetOrderInput(BaseModel):
    order_id: str


class GetTicketInput(BaseModel):
    ticket_id: str


class ListAccountTicketsInput(BaseModel):
    status: Literal["open", "closed", "all"] = "open"


class SearchDocumentsInput(BaseModel):
    query: str
    domain: str | None = None


class OrderToolResult(ToolResult):
    found: bool
    order_id: str | None = None
    status: str | None = None
    carrier: str | None = None
    booked_at: datetime | None = None
    pickup_window_start: datetime | None = None
    pickup_window_end: datetime | None = None
    pickup_actual_at: datetime | None = None
    pickup_delay_minutes: int | None = None
    booking_age_minutes: int | None = None
    shipment_fee_inr: Decimal | None = None
    carrier_fault: bool | None = None
    customer_fault: bool | None = None
    cancellation_requested_at: datetime | None = None


class TicketToolResult(ToolResult):
    found: bool
    ticket_id: str | None = None
    status: str | None = None
    subject: str | None = None
    description: str | None = None
    created_at: datetime | None = None
    last_customer_message_at: datetime | None = None
    assigned_to: str | None = None
    historical_resolution: str | None = None
    historical_resolution_authority: Literal["context_only"] | None = None


class AccountToolResult(ToolResult):
    found: bool
    account_id: str | None = None
    name: str | None = None
    plan: str | None = None
    status: str | None = None
    csm: str | None = None
    contract_file: str | None = None
    premium_support: bool | None = None


class TicketSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    ticket_id: str
    status: str
    subject: str
    created_at: datetime
    last_customer_message_at: datetime | None = None
    assigned_to: str | None = None


class ListAccountTicketsResult(ToolResult):
    tickets: list[TicketSummary]


class EvidenceItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_id: str
    source_name: str
    source_type: str
    section: str | None = None
    page: int | None = None
    authority_class: str
    domain: str
    content: str


class DocumentSearchResult(ToolResult):
    evidence: list[EvidenceItem]
    conflict_detected: bool
    requires_verification: bool
    resolution_note: str | None = None
