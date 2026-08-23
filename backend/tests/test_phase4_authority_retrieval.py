"""Tests for authority-aware retrieval decisions."""
from pathlib import Path

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.models import Account
from app.retrieval import DocumentRetriever, import_document_corpus
from app.schemas.auth import UserContext


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
def documents_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "data" / "documents"


async def _seed_documents(session: AsyncSession, documents_dir: Path) -> None:
    async with session.begin():
        session.add_all(
            [
                Account(id="ACCT-001", name="Northstar Logistics", plan="Enterprise", status="active"),
                Account(id="ACCT-002", name="LumenWorks", plan="Growth", status="active"),
                Account(id="ACCT-004", name="Generic Enterprise", plan="Enterprise", status="active"),
            ]
        )
        await import_document_corpus(session, documents_dir)


async def test_northstar_cancellation_prefers_customer_agreement(session: AsyncSession, documents_dir: Path) -> None:
    await _seed_documents(session, documents_dir)

    evidence_set = await DocumentRetriever(session).search(
        query="Can Northstar cancel a booked shipment without a cancellation fee?",
        context=UserContext(user_id="USR-001", role="customer", account_id="ACCT-001"),
    )

    source_ids = [item.source_id for item in evidence_set.evidence]
    assert source_ids[0] == "northstar_agreement"
    assert "cancellation_service_credit_sop_v4" in source_ids
    assert evidence_set.conflict_detected is False
    assert evidence_set.requires_verification is False
    assert evidence_set.authoritative_source == "northstar_agreement"
    assert evidence_set.explanation == "Customer agreement overrides default domain policy for this account."


async def test_lumenworks_service_credit_returns_agreement_plus_sop(session: AsyncSession, documents_dir: Path) -> None:
    await _seed_documents(session, documents_dir)

    evidence_set = await DocumentRetriever(session).search(
        query="LumenWorks failed pickup credit",
        context=UserContext(user_id="USR-002", role="customer", account_id="ACCT-002"),
    )

    source_ids = [item.source_id for item in evidence_set.evidence]
    assert source_ids[0] == "lumenworks_agreement"
    assert "cancellation_service_credit_sop_v4" in source_ids


async def test_enterprise_p1_sla_uses_current_policy_for_account_without_override(
    session: AsyncSession,
    documents_dir: Path,
) -> None:
    await _seed_documents(session, documents_dir)

    evidence_set = await DocumentRetriever(session).search(
        query="Enterprise P1 SLA",
        context=UserContext(user_id="USR-004", role="customer", account_id="ACCT-004"),
    )

    assert evidence_set.evidence[0].source_id == "support_policy_v3"
    assert "support_policy_v2" not in {item.source_id for item in evidence_set.evidence}


async def test_bulk_upload_limit_uses_product_operations_guide(session: AsyncSession, documents_dir: Path) -> None:
    await _seed_documents(session, documents_dir)

    evidence_set = await DocumentRetriever(session).search(
        query="Bulk upload limit",
        context=UserContext(user_id="USR-004", role="customer", account_id="ACCT-004"),
    )

    assert evidence_set.evidence[0].source_id == "product_operations_guide"


async def test_current_sla_request_never_uses_policy_v2_by_default(
    session: AsyncSession,
    documents_dir: Path,
) -> None:
    await _seed_documents(session, documents_dir)

    evidence_set = await DocumentRetriever(session).search(
        query="current P1 SLA",
        context=UserContext(user_id="USR-004", role="customer", account_id="ACCT-004"),
        limit=10,
    )

    assert "support_policy_v2" not in {item.source_id for item in evidence_set.evidence}


async def test_northstar_customer_cannot_retrieve_lumenworks_agreement(
    session: AsyncSession,
    documents_dir: Path,
) -> None:
    await _seed_documents(session, documents_dir)

    evidence_set = await DocumentRetriever(session).search(
        query="LumenWorks agreement",
        context=UserContext(user_id="USR-001", role="customer", account_id="ACCT-001"),
        limit=10,
    )

    assert "lumenworks_agreement" not in {item.source_id for item in evidence_set.evidence}
    assert all(item.account_id != "ACCT-002" for item in evidence_set.evidence)
