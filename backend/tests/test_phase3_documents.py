"""Tests for authority-aware PDF ingestion and retrieval."""
from pathlib import Path

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.models import Account, DocumentChunk, DocumentSource
from app.retrieval import DocumentRetriever, import_document_corpus


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


async def _seed_accounts(session: AsyncSession) -> None:
    session.add_all(
        [
            Account(id="ACCT-001", name="Northstar Logistics", plan="Enterprise", status="active"),
            Account(id="ACCT-002", name="LumenWorks", plan="Growth", status="active"),
        ]
    )


async def _seed_documents(session: AsyncSession, documents_dir: Path) -> None:
    async with session.begin():
        await _seed_accounts(session)
        await import_document_corpus(session, documents_dir)


async def test_document_sources_and_chunks_are_imported(session: AsyncSession, documents_dir: Path) -> None:
    await _seed_documents(session, documents_dir)

    source_count = await session.scalar(select(func.count()).select_from(DocumentSource))
    chunk_count = await session.scalar(select(func.count()).select_from(DocumentChunk))

    assert source_count == 6
    assert chunk_count >= 10


async def test_current_policy_excludes_deprecated_policy_by_default(
    session: AsyncSession,
    documents_dir: Path,
) -> None:
    await _seed_documents(session, documents_dir)

    evidence = await DocumentRetriever(session).search("Enterprise P1 SLA", account_id=None, limit=5)
    source_ids = {item.source_id for item in evidence}

    assert "support_policy_v3" in source_ids
    assert "support_policy_v2" not in source_ids


async def test_northstar_cancellation_returns_agreement_and_current_sop(
    session: AsyncSession,
    documents_dir: Path,
) -> None:
    await _seed_documents(session, documents_dir)

    evidence = await DocumentRetriever(session).search("Northstar cancellation fee", account_id="ACCT-001", limit=5)
    source_ids = {item.source_id for item in evidence}

    assert "northstar_agreement" in source_ids
    assert "cancellation_service_credit_sop_v4" in source_ids
    assert "lumenworks_agreement" not in source_ids


async def test_lumenworks_service_credit_returns_agreement_and_current_sop(
    session: AsyncSession,
    documents_dir: Path,
) -> None:
    await _seed_documents(session, documents_dir)

    evidence = await DocumentRetriever(session).search(
        "LumenWorks failed pickup credit",
        account_id="ACCT-002",
        limit=5,
    )
    source_ids = {item.source_id for item in evidence}

    assert "lumenworks_agreement" in source_ids
    assert "cancellation_service_credit_sop_v4" in source_ids


async def test_cross_account_retrieval_filters_before_ranking(
    session: AsyncSession,
    documents_dir: Path,
) -> None:
    await _seed_documents(session, documents_dir)

    evidence = await DocumentRetriever(session).search(
        "LumenWorks service credit",
        account_id="ACCT-001",
        limit=10,
    )

    assert evidence
    assert all(item.account_id != "ACCT-002" for item in evidence)
    assert "lumenworks_agreement" not in {item.source_id for item in evidence}
