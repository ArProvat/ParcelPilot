"""Operational domain models for ParcelPilot."""
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, JSON, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from app.db.base import Base
from app.db.types import embedding_column_type


metadata_json_type = JSON().with_variant(JSONB, "postgresql")


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    plan: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    csm: Mapped[str | None] = mapped_column(String(255))
    contract_file: Mapped[str | None] = mapped_column(String(255))
    premium_support: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)

    orders: Mapped[list["Order"]] = relationship(back_populates="account")
    tickets: Mapped[list["Ticket"]] = relationship(back_populates="account")
    escalations: Mapped[list["Escalation"]] = relationship(back_populates="account")


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), index=True, nullable=False)
    carrier: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(30), index=True, nullable=False)
    booked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    pickup_window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    pickup_window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    pickup_actual_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    shipment_fee_inr: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    carrier_fault: Mapped[bool] = mapped_column(Boolean, nullable=False)
    customer_fault: Mapped[bool] = mapped_column(Boolean, nullable=False)
    cancellation_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)

    account: Mapped[Account] = relationship(back_populates="orders")


class Ticket(Base):
    __tablename__ = "tickets"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(30), index=True, nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    channel: Mapped[str] = mapped_column(String(30), nullable=False)
    assigned_to: Mapped[str | None] = mapped_column(String(255))
    last_customer_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    historical_resolution: Mapped[str | None] = mapped_column(Text)

    account: Mapped[Account] = relationship(back_populates="tickets")
    escalations: Mapped[list["Escalation"]] = relationship(back_populates="ticket")


class DatasetConfig(Base):
    __tablename__ = "dataset_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    important_note: Mapped[str | None] = mapped_column(Text)


class ConversationThread(Base):
    __tablename__ = "conversation_threads"

    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    account_id: Mapped[str | None] = mapped_column(ForeignKey("accounts.id"), index=True)
    title: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    messages: Mapped[list["ConversationMessage"]] = relationship(
        back_populates="thread",
        cascade="all, delete-orphan",
    )


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    thread_id: Mapped[str] = mapped_column(ForeignKey("conversation_threads.id"), index=True, nullable=False)
    role: Mapped[str] = mapped_column(String(30), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", metadata_json_type, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    thread: Mapped[ConversationThread] = relationship(back_populates="messages")


class Escalation(Base):
    __tablename__ = "escalations"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), index=True, nullable=False)
    ticket_id: Mapped[str] = mapped_column(ForeignKey("tickets.id"), nullable=False)
    priority: Mapped[str] = mapped_column(String(30), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="open", nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(120), unique=True, index=True, nullable=False)

    account: Mapped[Account] = relationship(back_populates="escalations")
    ticket: Mapped[Ticket | None] = relationship(back_populates="escalations")


class PendingAction(Base):
    __tablename__ = "pending_actions"

    action_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    thread_id: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    tool_name: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(30), index=True, nullable=False)
    user_id: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    account_id: Mapped[str | None] = mapped_column(ForeignKey("accounts.id"), index=True)
    arguments: Mapped[dict[str, Any]] = mapped_column(metadata_json_type, default=dict, nullable=False)
    result: Mapped[dict[str, Any] | None] = mapped_column(metadata_json_type)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[str | None] = mapped_column(String(255), index=True)
    account_id: Mapped[str | None] = mapped_column(ForeignKey("accounts.id"), index=True)
    thread_id: Mapped[str | None] = mapped_column(String(255), index=True)
    event_type: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    resource_type: Mapped[str | None] = mapped_column(String(80))
    resource_id: Mapped[str | None] = mapped_column(String(255))
    tool_name: Mapped[str | None] = mapped_column(String(255))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)


class DocumentSource(Base):
    __tablename__ = "document_sources"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    source_key: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    source_name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(30), index=True, nullable=False)
    scope: Mapped[str] = mapped_column(String(30), index=True, nullable=False)
    account_id: Mapped[str | None] = mapped_column(ForeignKey("accounts.id"), index=True)
    authority_class: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    effective_at: Mapped[date | None] = mapped_column(Date)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", metadata_json_type, default=dict, nullable=False)

    chunks: Mapped[list["DocumentChunk"]] = relationship(back_populates="document", cascade="all, delete-orphan")


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("document_sources.id"), index=True, nullable=False)
    page: Mapped[int | None] = mapped_column(Integer)
    section: Mapped[str | None] = mapped_column(String(255), index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(embedding_column_type())
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", metadata_json_type, default=dict, nullable=False)

    document: Mapped[DocumentSource] = relationship(back_populates="chunks")
