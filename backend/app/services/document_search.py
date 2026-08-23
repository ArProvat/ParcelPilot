"""Service adapter for authority-aware document search tool results."""
from sqlalchemy.ext.asyncio import AsyncSession

from app.retrieval import DocumentRetriever
from app.schemas.auth import UserContext
from app.schemas.tools import DocumentSearchResult, EvidenceItem


class DocumentSearchService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def search(
        self,
        query: str,
        user: UserContext,
        domain: str | None = None,
    ) -> DocumentSearchResult:
        evidence_set = await DocumentRetriever(self.session).search(
            query=query,
            context=user,
            domain=domain,
        )
        return DocumentSearchResult(
            success=True,
            evidence=[
                EvidenceItem(
                    source_id=item.source_id,
                    source_name=item.source_name,
                    source_type=item.source_type,
                    section=item.section,
                    page=item.page,
                    authority_class=item.authority_class,
                    domain=item.domain,
                    content=item.content,
                )
                for item in evidence_set.evidence
            ],
            conflict_detected=evidence_set.conflict_detected,
            requires_verification=evidence_set.requires_verification,
            resolution_note=evidence_set.explanation,
        )
