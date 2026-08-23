"""Knowledge-base document management endpoints."""
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependency import get_db_session
from app.schemas.auth import UserContext
from app.schemas.documents import (
    AuthorityClassName,
    DocumentMutationResult,
    DocumentSourceSummary,
    SourceScope,
    SourceStatus,
    SourceType,
)
from app.security.auth import get_current_user
from app.services.document_admin import DocumentAdminService


router = APIRouter()


@router.get("", response_model=list[DocumentSourceSummary])
async def list_documents(
    user: UserContext = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    return await DocumentAdminService(session).list_sources(user)


@router.post("", response_model=DocumentMutationResult, status_code=status.HTTP_201_CREATED)
async def upload_or_update_document(
    file: Annotated[UploadFile, File(description="PDF file to parse, chunk, embed, and store")],
    source_key: Annotated[str, Form(description="Stable source key, e.g. support_policy_v4")],
    source_name: Annotated[str, Form(description="Human-readable source name")],
    source_type: Annotated[SourceType, Form()] = "product_documentation",
    status_: Annotated[SourceStatus, Form(alias="status")] = "current",
    scope: Annotated[SourceScope, Form()] = "global",
    authority_class: Annotated[AuthorityClassName, Form()] = "current_product_docs",
    account_id: Annotated[str | None, Form()] = None,
    effective_at: Annotated[date | None, Form()] = None,
    version: Annotated[str | None, Form()] = None,
    user: UserContext = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    async with session.begin():
        source = await DocumentAdminService(session).upsert_pdf(
            user=user,
            file=file,
            source_key=source_key,
            source_name=source_name,
            source_type=source_type,
            status_=status_,
            scope=scope,
            authority_class=authority_class,
            account_id=account_id,
            effective_at=effective_at,
            version=version,
        )
    return DocumentMutationResult(
        success=True,
        source=source,
        message="Document source uploaded and embedded.",
    )


@router.put("/{source_key}", response_model=DocumentMutationResult)
async def replace_document_version(
    source_key: str,
    file: Annotated[UploadFile, File(description="Replacement PDF file")],
    source_name: Annotated[str, Form(description="Human-readable source name")],
    source_type: Annotated[SourceType, Form()] = "product_documentation",
    status_: Annotated[SourceStatus, Form(alias="status")] = "current",
    scope: Annotated[SourceScope, Form()] = "global",
    authority_class: Annotated[AuthorityClassName, Form()] = "current_product_docs",
    account_id: Annotated[str | None, Form()] = None,
    effective_at: Annotated[date | None, Form()] = None,
    version: Annotated[str | None, Form()] = None,
    user: UserContext = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    async with session.begin():
        source = await DocumentAdminService(session).upsert_pdf(
            user=user,
            file=file,
            source_key=source_key,
            source_name=source_name,
            source_type=source_type,
            status_=status_,
            scope=scope,
            authority_class=authority_class,
            account_id=account_id,
            effective_at=effective_at,
            version=version,
        )
    return DocumentMutationResult(
        success=True,
        source=source,
        message="Document source replaced and re-embedded.",
    )


@router.delete("/{source_key}", response_model=DocumentMutationResult)
async def delete_document(
    source_key: str,
    user: UserContext = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    async with session.begin():
        deleted = await DocumentAdminService(session).delete_source(user=user, source_key=source_key)
    return DocumentMutationResult(
        success=deleted,
        source=None,
        message="Document source deleted from knowledge base." if deleted else "Document source not found.",
    )
