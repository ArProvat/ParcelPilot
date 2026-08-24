"""Authority-aware retrieval over document chunks."""
from __future__ import annotations

from dataclasses import dataclass
import re

from pgvector.sqlalchemy import Vector
from sqlalchemy import Float, bindparam, cast, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DocumentChunk, DocumentSource
from app.db.types import EMBEDDING_DIMENSION
from app.retrieval.authority import AuthorityClass, EvidenceDomain, authority_rank
from app.retrieval.embeddings import EmbeddingProvider, get_embedding_provider
from app.schemas.auth import UserContext
from app.schemas.evidence import Evidence, EvidenceSet
from app.security.authorization import require_permission


DEFAULT_VECTOR_CANDIDATES = 10
DEFAULT_FINAL_LIMIT = 6


@dataclass(frozen=True)
class _ScoredEvidence:
    source: DocumentSource
    chunk: DocumentChunk
    relevance_score: float


class DocumentRetriever:
    def __init__(
        self,
        session: AsyncSession,
        embedding_provider: EmbeddingProvider | None = None,
    ) -> None:
        self.session = session
        self.embedding_provider = embedding_provider or get_embedding_provider()

    async def search(
        self,
        query: str,
        context: UserContext | None = None,
        *,
        account_id: str | None = None,
        include_deprecated: bool = False,
        limit: int = DEFAULT_FINAL_LIMIT,
        vector_candidates: int = DEFAULT_VECTOR_CANDIDATES,
        domain: str | None = None,
    ) -> EvidenceSet:
        """Return authority-ranked evidence available to the authenticated user."""
        if context is None:
            context = UserContext(
                user_id="system",
                role="system",
                account_id=account_id,
                permissions=frozenset({"documents:read"}),
            )

        require_permission(context, "documents:read")

        normalized_query = _normalize_query(query)
        evidence_domain = None
        if domain:
            try:
                evidence_domain = EvidenceDomain(domain.lower().strip())
            except ValueError:
                evidence_domain = None
        if evidence_domain is None:
            evidence_domain = _infer_domain(normalized_query)

        retrieval_query = _expand_query_for_domain(normalized_query, evidence_domain)
        candidates = await self._retrieve_candidates(
            retrieval_query,
            context,
            include_deprecated=include_deprecated,
            vector_candidates=vector_candidates,
        )

        scored = self._score_candidates(retrieval_query, evidence_domain, candidates)
        ranked = _rank_and_dedupe(scored, evidence_domain)
        evidence = [_to_evidence(item) for item in ranked[:limit]]

        return _build_evidence_set(evidence, evidence_domain)

    async def _retrieve_candidates(
        self,
        query: str,
        context: UserContext,
        *,
        include_deprecated: bool,
        vector_candidates: int,
    ) -> list[tuple[DocumentChunk, DocumentSource, float | None]]:
        stmt = (
            select(DocumentChunk, DocumentSource)
            .join(DocumentSource, DocumentChunk.document_id == DocumentSource.id)
            .where(or_(DocumentSource.scope == "global", DocumentSource.account_id == context.account_id))
        )

        if not include_deprecated:
            stmt = stmt.where(DocumentSource.status == "current")

        if _is_postgres_session(self.session):
            query_embedding = self.embedding_provider.embed(query)
            distance = cast(
                DocumentChunk.embedding.op("<=>")(
                    bindparam("query_embedding", query_embedding, type_=Vector(EMBEDDING_DIMENSION))
                ),
                Float,
            ).label("distance")
            stmt = (
                stmt.add_columns(distance)
                .where(DocumentChunk.embedding.is_not(None))
                .order_by(distance)
                .limit(vector_candidates)
            )
            result = await self.session.execute(stmt)
            return [(chunk, source, _distance_to_relevance(distance_value)) for chunk, source, distance_value in result.all()]

        result = await self.session.execute(stmt)
        return [(chunk, source, None) for chunk, source in result.all()]

    def _score_candidates(
        self,
        query: str,
        domain: EvidenceDomain,
        candidates: list[tuple[DocumentChunk, DocumentSource, float | None]],
    ) -> list[_ScoredEvidence]:
        scored: list[_ScoredEvidence] = []
        for chunk, source, vector_relevance in candidates:
            chunk_domain = chunk.metadata_.get("domain", EvidenceDomain.GENERAL)
            lexical_relevance = _lexical_relevance(query, chunk.content, chunk_domain)
            relevance = max(lexical_relevance, vector_relevance or 0.0)

            if relevance <= 0:
                continue

            scored.append(_ScoredEvidence(source=source, chunk=chunk, relevance_score=relevance))
        return scored


def _rank_and_dedupe(scored: list[_ScoredEvidence], domain: EvidenceDomain) -> list[_ScoredEvidence]:
    scored.sort(key=lambda item: _rank_key(item, domain), reverse=True)

    deduped: list[_ScoredEvidence] = []
    seen: set[tuple[str, str | None]] = set()
    for item in scored:
        key = (item.source.source_key, item.chunk.section)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)

    return deduped


def _rank_key(item: _ScoredEvidence, query_domain: EvidenceDomain) -> tuple[bool, int, bool, float]:
    chunk_domain = item.chunk.metadata_.get("domain", EvidenceDomain.GENERAL)
    return (
        chunk_domain == query_domain,
        authority_rank(item.source.authority_class, query_domain),
        item.source.account_id is not None,
        item.relevance_score,
    )


def _to_evidence(item: _ScoredEvidence) -> Evidence:
    metadata = item.chunk.metadata_
    return Evidence(
        source_id=item.source.source_key,
        source_name=item.source.source_name,
        source_type=item.source.source_type,
        section=item.chunk.section,
        page=item.chunk.page,
        domain=metadata.get("domain", EvidenceDomain.GENERAL),
        authority_class=item.source.authority_class,
        status=item.source.status,
        account_id=item.source.account_id,
        content=item.chunk.content,
        relevance_score=item.relevance_score,
    )


def _build_evidence_set(evidence: list[Evidence], domain: EvidenceDomain) -> EvidenceSet:
    authoritative = evidence[0].source_id if evidence else None
    explanation = None
    conflict_detected = False
    requires_verification = False

    if _has_agreement_and_domain_policy(evidence):
        explanation = "Customer agreement overrides default domain policy for this account."
    elif _has_unresolved_same_authority_conflict(evidence, domain):
        conflict_detected = True
        requires_verification = True
        explanation = "Multiple equally authoritative current sources appear to disagree; verify before state-changing action."

    return EvidenceSet(
        evidence=evidence,
        conflict_detected=conflict_detected,
        authoritative_source=authoritative,
        explanation=explanation,
        requires_verification=requires_verification,
    )


def _has_agreement_and_domain_policy(evidence: list[Evidence]) -> bool:
    authorities = {item.authority_class for item in evidence}
    return (
        AuthorityClass.CUSTOMER_AGREEMENT in authorities
        and AuthorityClass.CURRENT_DOMAIN_POLICY in authorities
    )


def _has_unresolved_same_authority_conflict(evidence: list[Evidence], domain: EvidenceDomain) -> bool:
    current_same_domain = [
        item
        for item in evidence
        if item.status == "current"
        and item.domain == domain
        and item.authority_class != AuthorityClass.CUSTOMER_AGREEMENT
    ]
    authorities = {item.authority_class for item in current_same_domain}
    return len(current_same_domain) > 1 and len(authorities) == 1


def _normalize_query(query: str) -> str:
    return re.sub(r"\s+", " ", query.strip().lower())


def _infer_domain(query: str) -> EvidenceDomain:
    if "cancel" in query or "cancellation" in query:
        return EvidenceDomain.CANCELLATION
    if "credit" in query or "failed pickup" in query or "failed-pickup" in query:
        return EvidenceDomain.SERVICE_CREDIT
    if "sla" in query or "p1" in query or "p2" in query or "p3" in query or "severity" in query:
        return EvidenceDomain.SUPPORT_SLA
    if "bulk upload" in query or "upload limit" in query or "plan" in query:
        return EvidenceDomain.PLAN_ENTITLEMENT
    if "known issue" in query or "webhook" in query or "ki-" in query:
        return EvidenceDomain.KNOWN_ISSUE
    if "shipment status" in query or "booked" in query or "picked_up" in query:
        return EvidenceDomain.SHIPMENT_STATUS
    return EvidenceDomain.GENERAL


def _expand_query_for_domain(query: str, domain: EvidenceDomain) -> str:
    expansions = {
        EvidenceDomain.CANCELLATION: "order booked shipment charge waiver customer agreement fee",
        EvidenceDomain.SERVICE_CREDIT: "failed pickup carrier fault threshold amount sop customer agreement",
        EvidenceDomain.SUPPORT_SLA: "severity first response target support policy",
        EvidenceDomain.PLAN_ENTITLEMENT: "plan capability supported file rows csv",
        EvidenceDomain.KNOWN_ISSUE: "status workaround investigating monitoring",
    }
    expansion = expansions.get(domain)
    if expansion is None:
        return query
    return f"{query} {expansion}"


def _lexical_relevance(query: str, content: str, domain: str | EvidenceDomain | None) -> float:
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
    stopwords = {"a", "an", "and", "are", "can", "for", "is", "my", "of", "the", "this", "to", "what", "without"}
    return {token for token in re.findall(r"[a-z0-9]+", text.lower()) if token not in stopwords}


def _domain_boost(query: str, domain: str | EvidenceDomain | None) -> float:
    if domain == EvidenceDomain.CANCELLATION and ("cancel" in query or "cancellation" in query):
        return 0.35
    if domain == EvidenceDomain.SERVICE_CREDIT and ("credit" in query or "failed pickup" in query or "failed-pickup" in query):
        return 0.35
    if domain == EvidenceDomain.SUPPORT_SLA and ("sla" in query or "p1" in query or "p2" in query or "p3" in query):
        return 0.35
    if domain == EvidenceDomain.PLAN_ENTITLEMENT and ("bulk upload" in query or "upload limit" in query):
        return 0.35
    if domain == EvidenceDomain.KNOWN_ISSUE and ("known issue" in query or "webhook" in query):
        return 0.35
    return 0.0


def _phrase_boost(query: str, content: str) -> float:
    content_lower = content.lower()
    boost = 0.0
    for phrase in (
        "northstar",
        "lumenworks",
        "enterprise",
        "growth",
        "booked",
        "4 hours",
        "inr 300",
        "bulk upload",
        "5,000",
    ):
        if phrase in query and phrase in content_lower:
            boost += 0.15
    return boost


def _distance_to_relevance(distance: float | None) -> float:
    if distance is None:
        return 0.0
    return 1.0 / (1.0 + float(distance))


def _is_postgres_session(session: AsyncSession) -> bool:
    bind = session.get_bind()
    return bind.dialect.name == "postgresql"
