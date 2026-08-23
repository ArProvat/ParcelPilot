"""Idempotent startup bootstrap for candidate workbook and PDF data."""
from __future__ import annotations

from pathlib import Path
import logging

from sqlalchemy import func, select

from app.config import settings
from app.db.session import AsyncSessionLocal
from app.ingestion.workbook_loader import load_workbook_data
from app.ingestion.workbook import import_workbook_data
from app.models import Account, DocumentChunk, DocumentSource, Order, Ticket
from app.retrieval import import_document_corpus


logger = logging.getLogger(__name__)


async def bootstrap_candidate_data(data_dir: str | Path | None = None) -> dict[str, int | str]:
    """Load workbook and document corpus.

    Imports are idempotent: workbook rows use SQLAlchemy ``merge`` and document
    sources/chunks use deterministic UUIDs. Re-running startup updates the
    current snapshot without duplicating operational or vector data.
    """
    root = Path(data_dir or settings.DATA_DIR).resolve()
    workbook_path = root / "ParcelPilot_Assessment_Data.xlsx"
    documents_dir = root / "documents"

    if not workbook_path.exists():
        raise FileNotFoundError(f"Workbook not found: {workbook_path}")
    if not documents_dir.exists():
        raise FileNotFoundError(f"Documents directory not found: {documents_dir}")

    workbook = load_workbook_data(workbook_path)
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await import_workbook_data(session, workbook)
            chunks = await import_document_corpus(session, documents_dir)

        counts = {
            "accounts": await _count(session, Account),
            "orders": await _count(session, Order),
            "tickets": await _count(session, Ticket),
            "document_sources": await _count(session, DocumentSource),
            "document_chunks": await _count(session, DocumentChunk),
            "snapshot_at": workbook.metadata.snapshot_at.isoformat(),
        }

    logger.info("bootstrap_completed", extra={"parcelpilot": counts})
    return counts


async def _count(session, model) -> int:
    value = await session.scalar(select(func.count()).select_from(model))
    return int(value or 0)


async def _main() -> None:
    counts = await bootstrap_candidate_data()
    print(f"Bootstrap complete: {counts}")


if __name__ == "__main__":
    import asyncio

    asyncio.run(_main())
