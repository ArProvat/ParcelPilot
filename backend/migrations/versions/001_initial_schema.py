"""create parcelpilot schema

Revision ID: 001_initial_schema
Revises:
Create Date: 2026-08-23 00:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql


revision: str = "001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "accounts",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("plan", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("csm", sa.String(length=255), nullable=True),
        sa.Column("contract_file", sa.String(length=255), nullable=True),
        sa.Column("premium_support", sa.Boolean(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_accounts_plan"), "accounts", ["plan"], unique=False)

    op.create_table(
        "document_sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_key", sa.String(length=100), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("source_name", sa.String(length=255), nullable=False),
        sa.Column("source_type", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("scope", sa.String(length=30), nullable=False),
        sa.Column("account_id", sa.String(length=32), nullable=True),
        sa.Column("authority_class", sa.String(length=80), nullable=False),
        sa.Column("effective_at", sa.Date(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_key"),
    )
    op.create_index(op.f("ix_document_sources_account_id"), "document_sources", ["account_id"], unique=False)
    op.create_index(op.f("ix_document_sources_authority_class"), "document_sources", ["authority_class"], unique=False)
    op.create_index(op.f("ix_document_sources_scope"), "document_sources", ["scope"], unique=False)
    op.create_index(op.f("ix_document_sources_source_key"), "document_sources", ["source_key"], unique=False)
    op.create_index(op.f("ix_document_sources_source_type"), "document_sources", ["source_type"], unique=False)
    op.create_index(op.f("ix_document_sources_status"), "document_sources", ["status"], unique=False)

    op.create_table(
        "document_chunks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("section", sa.String(length=255), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(1024), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["document_sources.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_document_chunks_document_id"), "document_chunks", ["document_id"], unique=False)
    op.create_index(op.f("ix_document_chunks_section"), "document_chunks", ["section"], unique=False)

    op.create_table(
        "dataset_config",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("snapshot_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("important_note", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "conversation_threads",
        sa.Column("id", sa.String(length=120), nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("account_id", sa.String(length=32), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_conversation_threads_account_id"), "conversation_threads", ["account_id"], unique=False)
    op.create_index(op.f("ix_conversation_threads_user_id"), "conversation_threads", ["user_id"], unique=False)

    op.create_table(
        "conversation_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("thread_id", sa.String(length=120), nullable=False),
        sa.Column("role", sa.String(length=30), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["thread_id"], ["conversation_threads.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_conversation_messages_thread_id"), "conversation_messages", ["thread_id"], unique=False)

    op.create_table(
        "orders",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("account_id", sa.String(length=32), nullable=False),
        sa.Column("carrier", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("booked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("pickup_window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("pickup_window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("pickup_actual_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("shipment_fee_inr", sa.Numeric(12, 2), nullable=False),
        sa.Column("carrier_fault", sa.Boolean(), nullable=False),
        sa.Column("customer_fault", sa.Boolean(), nullable=False),
        sa.Column("cancellation_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_orders_account_id"), "orders", ["account_id"], unique=False)
    op.create_index(op.f("ix_orders_status"), "orders", ["status"], unique=False)

    op.create_table(
        "tickets",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("account_id", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("channel", sa.String(length=30), nullable=False),
        sa.Column("assigned_to", sa.String(length=255), nullable=True),
        sa.Column("last_customer_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("historical_resolution", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_tickets_account_id"), "tickets", ["account_id"], unique=False)
    op.create_index(op.f("ix_tickets_created_at"), "tickets", ["created_at"], unique=False)
    op.create_index(op.f("ix_tickets_status"), "tickets", ["status"], unique=False)

    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=True),
        sa.Column("account_id", sa.String(length=32), nullable=True),
        sa.Column("thread_id", sa.String(length=255), nullable=True),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("resource_type", sa.String(length=80), nullable=True),
        sa.Column("resource_id", sa.String(length=255), nullable=True),
        sa.Column("tool_name", sa.String(length=255), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_audit_events_account_id"), "audit_events", ["account_id"], unique=False)
    op.create_index(op.f("ix_audit_events_created_at"), "audit_events", ["created_at"], unique=False)
    op.create_index(op.f("ix_audit_events_event_type"), "audit_events", ["event_type"], unique=False)
    op.create_index(op.f("ix_audit_events_thread_id"), "audit_events", ["thread_id"], unique=False)
    op.create_index(op.f("ix_audit_events_user_id"), "audit_events", ["user_id"], unique=False)

    op.create_table(
        "pending_actions",
        sa.Column("action_id", sa.Uuid(), nullable=False),
        sa.Column("thread_id", sa.String(length=255), nullable=False),
        sa.Column("tool_name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("account_id", sa.String(length=32), nullable=True),
        sa.Column("arguments", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"]),
        sa.PrimaryKeyConstraint("action_id"),
    )
    op.create_index(op.f("ix_pending_actions_account_id"), "pending_actions", ["account_id"], unique=False)
    op.create_index(op.f("ix_pending_actions_status"), "pending_actions", ["status"], unique=False)
    op.create_index(op.f("ix_pending_actions_thread_id"), "pending_actions", ["thread_id"], unique=False)
    op.create_index(op.f("ix_pending_actions_tool_name"), "pending_actions", ["tool_name"], unique=False)
    op.create_index(op.f("ix_pending_actions_user_id"), "pending_actions", ["user_id"], unique=False)

    op.create_table(
        "escalations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.String(length=32), nullable=False),
        sa.Column("ticket_id", sa.String(length=32), nullable=False),
        sa.Column("priority", sa.String(length=30), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("idempotency_key", sa.String(length=120), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index(op.f("ix_escalations_account_id"), "escalations", ["account_id"], unique=False)
    op.create_index(op.f("ix_escalations_idempotency_key"), "escalations", ["idempotency_key"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_document_chunks_section"), table_name="document_chunks")
    op.drop_index(op.f("ix_document_chunks_document_id"), table_name="document_chunks")
    op.drop_table("document_chunks")
    op.drop_index(op.f("ix_document_sources_status"), table_name="document_sources")
    op.drop_index(op.f("ix_document_sources_source_type"), table_name="document_sources")
    op.drop_index(op.f("ix_document_sources_source_key"), table_name="document_sources")
    op.drop_index(op.f("ix_document_sources_scope"), table_name="document_sources")
    op.drop_index(op.f("ix_document_sources_authority_class"), table_name="document_sources")
    op.drop_index(op.f("ix_document_sources_account_id"), table_name="document_sources")
    op.drop_table("document_sources")
    op.drop_index(op.f("ix_escalations_idempotency_key"), table_name="escalations")
    op.drop_index(op.f("ix_escalations_account_id"), table_name="escalations")
    op.drop_table("escalations")
    op.drop_index(op.f("ix_pending_actions_user_id"), table_name="pending_actions")
    op.drop_index(op.f("ix_pending_actions_tool_name"), table_name="pending_actions")
    op.drop_index(op.f("ix_pending_actions_thread_id"), table_name="pending_actions")
    op.drop_index(op.f("ix_pending_actions_status"), table_name="pending_actions")
    op.drop_index(op.f("ix_pending_actions_account_id"), table_name="pending_actions")
    op.drop_table("pending_actions")
    op.drop_index(op.f("ix_audit_events_user_id"), table_name="audit_events")
    op.drop_index(op.f("ix_audit_events_thread_id"), table_name="audit_events")
    op.drop_index(op.f("ix_audit_events_event_type"), table_name="audit_events")
    op.drop_index(op.f("ix_audit_events_created_at"), table_name="audit_events")
    op.drop_index(op.f("ix_audit_events_account_id"), table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index(op.f("ix_tickets_status"), table_name="tickets")
    op.drop_index(op.f("ix_tickets_created_at"), table_name="tickets")
    op.drop_index(op.f("ix_tickets_account_id"), table_name="tickets")
    op.drop_table("tickets")
    op.drop_index(op.f("ix_conversation_messages_thread_id"), table_name="conversation_messages")
    op.drop_table("conversation_messages")
    op.drop_index(op.f("ix_conversation_threads_user_id"), table_name="conversation_threads")
    op.drop_index(op.f("ix_conversation_threads_account_id"), table_name="conversation_threads")
    op.drop_table("conversation_threads")
    op.drop_index(op.f("ix_orders_status"), table_name="orders")
    op.drop_index(op.f("ix_orders_account_id"), table_name="orders")
    op.drop_table("orders")
    op.drop_table("dataset_config")
    op.drop_index(op.f("ix_accounts_plan"), table_name="accounts")
    op.drop_table("accounts")
