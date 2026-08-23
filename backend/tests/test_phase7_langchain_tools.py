"""Tests for LangChain-facing tool integration."""
from pathlib import Path

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.agent import SYSTEM_PROMPT, create_parcelpilot_agent
from app.db.base import Base
from app.ingestion import load_workbook_data
from app.ingestion.workbook import import_workbook_data
from app.retrieval import import_document_corpus
from app.schemas.auth import UserContext
from app.tools import create_agent_tools


class BindableFakeChatModel(FakeListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


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
    workbook = load_workbook_data(Path(__file__).resolve().parents[2] / "data" / "ParcelPilot_Assessment_Data.xlsx")
    documents_dir = Path(__file__).resolve().parents[2] / "data" / "documents"
    async with factory() as session:
        async with session.begin():
            await import_workbook_data(session, workbook)
            await import_document_corpus(session, documents_dir)

    yield factory
    await engine.dispose()


def northstar_user() -> UserContext:
    return UserContext(
        user_id="USR-NORTHSTAR-1",
        role="customer",
        account_id="ACCT-001",
        permissions=frozenset({"accounts:read", "orders:read", "tickets:read", "documents:read"}),
    )


def test_agent_tool_registry_exposes_safe_capabilities(session_factory) -> None:
    tools = {tool.name: tool for tool in create_agent_tools(northstar_user(), session_factory=session_factory)}

    assert set(tools) == {
        "search_documents",
        "get_order",
        "get_ticket",
        "get_my_account",
        "list_account_tickets",
        "evaluate_cancellation",
        "evaluate_service_credit",
        "evaluate_ticket_sla",
        "create_escalation",
    }
    assert set(tools["get_order"].args_schema.model_fields) == {"order_id"}
    assert set(tools["get_ticket"].args_schema.model_fields) == {"ticket_id"}
    assert set(tools["search_documents"].args_schema.model_fields) == {"query", "domain"}
    assert "account_id" not in tools["search_documents"].args_schema.model_fields
    assert set(tools["create_escalation"].args_schema.model_fields) == {"ticket_id", "priority", "reason"}
    assert "does not determine policy eligibility" in tools["get_order"].description
    assert "Do not use this for order or ticket records" in tools["search_documents"].description


async def test_search_documents_tool_returns_authority_aware_evidence(session_factory) -> None:
    tools = {tool.name: tool for tool in create_agent_tools(northstar_user(), session_factory=session_factory)}

    result = await tools["search_documents"].ainvoke(
        {"query": "Northstar cancellation terms for booked shipment", "domain": "cancellation"}
    )
    source_ids = {item["source_id"] for item in result["evidence"]}

    assert result["success"] is True
    assert "northstar_agreement" in source_ids
    assert "cancellation_service_credit_sop_v4" in source_ids
    assert "lumenworks_agreement" not in source_ids
    assert result["conflict_detected"] is False


async def test_tool_orchestration_foundation_order_then_documents(session_factory) -> None:
    tools = {tool.name: tool for tool in create_agent_tools(northstar_user(), session_factory=session_factory)}

    order_result = await tools["get_order"].ainvoke({"order_id": "ORD-1001"})
    document_result = await tools["search_documents"].ainvoke(
        {"query": "Can Northstar cancel a booked shipment without a fee?", "domain": "cancellation"}
    )

    assert order_result["found"] is True
    assert order_result["status"] == "BOOKED"
    assert "account_id" not in order_result
    assert document_result["evidence"][0]["source_id"] == "northstar_agreement"


def test_agent_factory_registers_prompt_tools_and_context(session_factory) -> None:
    model = BindableFakeChatModel(responses=["Done"])

    agent = create_parcelpilot_agent(
        model=model,
        user=northstar_user(),
        session_factory=session_factory,
    )

    assert agent is not None
    assert "Use tools whenever an answer depends" in SYSTEM_PROMPT
    assert "Historical ticket resolutions are context only" in SYSTEM_PROMPT
