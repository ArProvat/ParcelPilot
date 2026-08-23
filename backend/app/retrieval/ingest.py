"""Import PDF document sources and chunks into the database."""
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DocumentChunk, DocumentSource
from app.retrieval.embeddings import EmbeddingProvider, HashEmbeddingProvider
from app.retrieval.pdf_parser import ParsedChunk, parse_pdf_sections
from app.retrieval.source_registry import DOCUMENT_SOURCES, SourceDefinition


def _source_id(source: SourceDefinition):
    return uuid5(NAMESPACE_URL, f"parcelpilot:document-source:{source.source_key}")


def _chunk_id(chunk: ParsedChunk):
    return uuid5(
        NAMESPACE_URL,
        f"parcelpilot:document-chunk:{chunk.source.source_key}:{chunk.page}:{chunk.chunk_index}",
    )


async def import_document_corpus(
    session: AsyncSession,
    documents_dir: str | Path,
    embedding_provider: EmbeddingProvider | None = None,
) -> list[ParsedChunk]:
    provider = embedding_provider or HashEmbeddingProvider()
    base_path = Path(documents_dir)
    parsed_chunks: list[ParsedChunk] = []

    for source in DOCUMENT_SOURCES:
        source_path = base_path / source.filename
        if not source_path.exists():
            raise FileNotFoundError(f"Document source not found: {source_path}")

        document = DocumentSource(
            id=_source_id(source),
            source_key=source.source_key,
            filename=source.filename,
            source_name=source.source_name,
            source_type=source.source_type,
            status=source.status,
            scope=source.scope,
            account_id=source.account_id,
            authority_class=source.authority_class,
            effective_at=source.effective_at,
            metadata_=source.metadata,
        )
        await session.merge(document)

        for chunk in parse_pdf_sections(source_path, source):
            parsed_chunks.append(chunk)
            metadata = {
                "source_id": source.source_key,
                "filename": source.filename,
                "page": chunk.page,
                "section": chunk.section,
                "source_type": source.source_type,
                "status": source.status,
                "scope": source.scope,
                "account_id": source.account_id,
                "authority_class": source.authority_class,
                "domain": chunk.domain,
            }
            await session.merge(
                DocumentChunk(
                    id=_chunk_id(chunk),
                    document_id=_source_id(source),
                    page=chunk.page,
                    section=chunk.section,
                    content=chunk.content,
                    embedding=provider.embed(chunk.content),
                    metadata_=metadata,
                )
            )

    return parsed_chunks


async def _main() -> None:
    import argparse

    from app.db.session import AsyncSessionLocal

    parser = argparse.ArgumentParser(description="Import ParcelPilot PDF documents into PostgreSQL.")
    parser.add_argument(
        "documents_dir",
        nargs="?",
        default=str(Path(__file__).resolve().parents[3] / "data" / "documents"),
    )
    args = parser.parse_args()

    async with AsyncSessionLocal() as session:
        async with session.begin():
            chunks = await import_document_corpus(session, args.documents_dir)
    print(f"Imported {len(chunks)} authority-aware document chunks.")


if __name__ == "__main__":
    import asyncio

    asyncio.run(_main())
