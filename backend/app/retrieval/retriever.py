"""Authority-aware retrieval over document chunks."""
import re

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DocumentChunk, DocumentSource
from app.schemas.evidence import Evidence


AUTHORITY_RANK = {
    "signed_customer_agreement": 100,
    "current_policy": 80,
    "current_sop": 70,
    "current_product_documentation": 60,
    "deprecated": 10,
}


class DocumentRetriever:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def search(
        self,
        query: str,
        account_id: str | None,
        *,
        include_deprecated: bool = False,
        limit: int = 5,
    ) -> list[Evidence]:
        stmt = (
            select(DocumentChunk, DocumentSource)
            .join(DocumentSource, DocumentChunk.document_id == DocumentSource.id)
            .where(or_(DocumentSource.scope == "global", DocumentSource.account_id == account_id))
        )

        if not include_deprecated:
            stmt = stmt.where(DocumentSource.status == "current")

        result = await self.session.execute(stmt)
        candidates = result.all()

        scored = []
        for chunk, source in candidates:
            relevance = _lexical_relevance(query, chunk.content, chunk.metadata_.get("domain"))
            if relevance <= 0:
                continue
            scored.append((source, chunk, relevance))

        scored.sort(
            key=lambda row: (
                row[2],
                AUTHORITY_RANK.get(row[0].authority_class, 0),
            ),
            reverse=True,
        )

        return [
            Evidence(
                source_id=source.source_key,
                source_name=source.source_name,
                source_type=source.source_type,
                section=chunk.section,
                page=chunk.page,
                authority_class=source.authority_class,
                status=source.status,
                account_id=source.account_id,
                content=chunk.content,
                relevance_score=relevance,
            )
            for source, chunk, relevance in scored[:limit]
        ]


def _lexical_relevance(query: str, content: str, domain: str | None) -> float:
    query_tokens = _tokens(query)
    content_tokens = _tokens(content)
    if not query_tokens or not content_tokens:
        return 0.0

    overlap = query_tokens & content_tokens
    score = len(overlap) / len(query_tokens)

    domain_boost = _domain_boost(query, domain)
    phrase_boost = _phrase_boost(query, content)
    return score + domain_boost + phrase_boost


def _tokens(text: str) -> set[str]:
    stopwords = {"a", "an", "and", "are", "for", "is", "my", "of", "the", "to", "what"}
    return {token for token in re.findall(r"[a-z0-9]+", text.lower()) if token not in stopwords}


def _domain_boost(query: str, domain: str | None) -> float:
    query = query.lower()
    if domain == "cancellation" and ("cancel" in query or "cancellation" in query):
        return 0.35
    if domain == "service_credit" and ("credit" in query or "failed pickup" in query or "failed-pickup" in query):
        return 0.35
    if domain == "support_sla" and ("sla" in query or "p1" in query or "p2" in query or "p3" in query):
        return 0.35
    return 0.0


def _phrase_boost(query: str, content: str) -> float:
    query_lower = query.lower()
    content_lower = content.lower()
    boost = 0.0
    for phrase in ("northstar", "lumenworks", "enterprise", "growth", "booked", "4 hours", "inr 300"):
        if phrase in query_lower and phrase in content_lower:
            boost += 0.15
    return boost
