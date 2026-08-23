"""Schemas for knowledge-base document management."""
from datetime import date
from typing import Literal

from pydantic import BaseModel


SourceType = Literal[
    "support_policy",
    "sop",
    "product_documentation",
    "customer_agreement",
    "historical_ticket",
    "other",
]

SourceStatus = Literal["current", "deprecated", "historical"]
SourceScope = Literal["global", "customer"]
AuthorityClassName = Literal[
    "signed_customer_agreement",
    "current_domain_policy",
    "current_policy",
    "current_product_docs",
    "historical_context",
    "deprecated",
]


class DocumentSourceSummary(BaseModel):
    source_key: str
    source_name: str
    filename: str
    source_type: str
    status: str
    scope: str
    account_id: str | None
    authority_class: str
    effective_at: date | None
    version: str | None
    chunk_count: int


class DocumentMutationResult(BaseModel):
    success: bool
    source: DocumentSourceSummary | None = None
    message: str
