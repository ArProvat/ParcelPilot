"""Administrative document knowledge-base management."""
from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from uuid import NAMESPACE_URL, uuid5

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DocumentChunk, DocumentSource
from app.repositories.audit_events import AuditEventRepository
from app.retrieval.embeddings import EmbeddingProvider, get_embedding_provider
from app.retrieval.pdf_parser import parse_pdf_sections
from app.retrieval.source_registry import SourceDefinition
from app.schemas.auth import UserContext
from app.schemas.documents import DocumentSourceSummary
from app.security.authorization import AuthorizationError, require_permission


SOURCE_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,98}[a-z0-9]$")


class DocumentAdminService:
    def __init__(
        self,
        session: AsyncSession,
        embedding_provider: EmbeddingProvider | None = None,
    ) -> None:
        self.session = session
        self._embedding_provider = embedding_provider

    async def list_sources(self, user: UserContext) -> list[DocumentSourceSummary]:
        self._require_write_access(user)
        chunk_count = func.count(DocumentChunk.id).label("chunk_count")
        stmt = (
            select(DocumentSource, chunk_count)
            .outerjoin(DocumentChunk, DocumentChunk.document_id == DocumentSource.id)
            .group_by(DocumentSource.id)
            .order_by(DocumentSource.source_key)
        )
        rows = (await self.session.execute(stmt)).all()
        return [self._summary(source, int(count or 0)) for source, count in rows]

    async def upsert_pdf(
        self,
        *,
        user: UserContext,
        file: UploadFile,
        source_key: str,
        source_name: str,
        source_type: str,
        status_: str,
        scope: str,
        authority_class: str,
        account_id: str | None,
        effective_at: date | None,
        version: str | None,
    ) -> DocumentSourceSummary:
        self._require_write_access(user)
        source_key = _normalize_source_key(source_key)
        _validate_source_key(source_key)
        _validate_scope(scope, account_id)
        _validate_pdf_file(file)

        filename = Path(file.filename or f"{source_key}.pdf").name
        content = await file.read()
        if not content:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded PDF is empty")

        source = SourceDefinition(
            source_key=source_key,
            filename=filename,
            source_name=source_name,
            source_type=source_type,
            status=status_,
            scope=scope,
            account_id=account_id,
            authority_class=authority_class,
            effective_at=effective_at,
            metadata={
                "version": version or "",
                "uploaded_by": user.user_id,
                "uploaded_at": datetime.now(timezone.utc).isoformat(),
                "managed_by": "api",
            },
        )

        source_id = _source_id(source_key)
        with TemporaryDirectory(prefix="parcelpilot_pdf_") as tmpdir:
            path = Path(tmpdir) / filename
            path.write_bytes(content)
            try:
                parsed_chunks = parse_pdf_sections(path, source)
            except Exception as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Could not parse uploaded PDF: {exc.__class__.__name__}",
                ) from exc

        if not parsed_chunks:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No searchable text found in PDF")

        await self.session.execute(delete(DocumentChunk).where(DocumentChunk.document_id == source_id))
        await self.session.merge(
            DocumentSource(
                id=source_id,
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
        )

        for chunk in parsed_chunks:
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
                "version": version,
            }
            self.session.add(
                DocumentChunk(
                    id=_chunk_id(source_key, chunk.page, chunk.chunk_index),
                    document_id=source_id,
                    page=chunk.page,
                    section=chunk.section,
                    content=chunk.content,
                    embedding=self.embedding_provider.embed(chunk.content),
                    metadata_=metadata,
                )
            )

        await AuditEventRepository(self.session).record(
            event_type="DOCUMENT_UPSERTED",
            user_id=user.user_id,
            account_id=account_id,
            thread_id=None,
            resource_type="document_source",
            resource_id=source_key,
            tool_name=None,
            payload={
                "source_key": source_key,
                "filename": filename,
                "version": version,
                "chunk_count": len(parsed_chunks),
            },
            created_at=datetime.now(timezone.utc),
        )
        await self.session.flush()
        return self._summary_from_values(source, len(parsed_chunks))

    async def delete_source(self, *, user: UserContext, source_key: str) -> bool:
        self._require_write_access(user)
        source_key = _normalize_source_key(source_key)
        source_id = _source_id(source_key)

        source = await self.session.scalar(
            select(DocumentSource).where(DocumentSource.source_key == source_key)
        )
        if source is None:
            return False

        await self.session.execute(delete(DocumentChunk).where(DocumentChunk.document_id == source_id))
        await self.session.delete(source)
        await AuditEventRepository(self.session).record(
            event_type="DOCUMENT_DELETED",
            user_id=user.user_id,
            account_id=source.account_id,
            thread_id=None,
            resource_type="document_source",
            resource_id=source_key,
            tool_name=None,
            payload={"source_key": source_key, "filename": source.filename},
            created_at=datetime.now(timezone.utc),
        )
        await self.session.flush()
        return True

    def _require_write_access(self, user: UserContext) -> None:
        try:
            require_permission(user, "documents:write")
        except AuthorizationError as exc:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    @property
    def embedding_provider(self) -> EmbeddingProvider:
        if self._embedding_provider is None:
            self._embedding_provider = get_embedding_provider()
        return self._embedding_provider

    def _summary(self, source: DocumentSource, chunk_count: int) -> DocumentSourceSummary:
        return DocumentSourceSummary(
            source_key=source.source_key,
            source_name=source.source_name,
            filename=source.filename,
            source_type=source.source_type,
            status=source.status,
            scope=source.scope,
            account_id=source.account_id,
            authority_class=source.authority_class,
            effective_at=source.effective_at,
            version=source.metadata_.get("version") if source.metadata_ else None,
            chunk_count=chunk_count,
        )

    def _summary_from_values(self, source: SourceDefinition, chunk_count: int) -> DocumentSourceSummary:
        return DocumentSourceSummary(
            source_key=source.source_key,
            source_name=source.source_name,
            filename=source.filename,
            source_type=source.source_type,
            status=source.status,
            scope=source.scope,
            account_id=source.account_id,
            authority_class=source.authority_class,
            effective_at=source.effective_at,
            version=source.metadata.get("version") or None,
            chunk_count=chunk_count,
        )


def _source_id(source_key: str):
    return uuid5(NAMESPACE_URL, f"parcelpilot:document-source:{source_key}")


def _chunk_id(source_key: str, page: int | None, chunk_index: int):
    return uuid5(NAMESPACE_URL, f"parcelpilot:document-chunk:{source_key}:{page}:{chunk_index}")


def _normalize_source_key(source_key: str) -> str:
    return source_key.strip().lower().replace(" ", "_")


def _validate_source_key(source_key: str) -> None:
    if not SOURCE_KEY_RE.match(source_key):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="source_key must be 3-100 chars and contain only lowercase letters, numbers, _ or -",
        )


def _validate_scope(scope: str, account_id: str | None) -> None:
    if scope == "customer" and not account_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="account_id is required when scope=customer",
        )


def _validate_pdf_file(file: UploadFile) -> None:
    filename = file.filename or ""
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only PDF uploads are supported")
