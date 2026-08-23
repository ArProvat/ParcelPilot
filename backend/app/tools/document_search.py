"""LangChain document search tool backed by authorized retrieval."""
from collections.abc import Callable
from typing import Any

from langchain_core.tools import StructuredTool
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.auth import UserContext
from app.schemas.tools import SearchDocumentsInput
from app.services.document_search import DocumentSearchService


SessionFactory = Callable[[], AsyncSession]


def create_document_search_tools(
    user: UserContext,
    session_factory: SessionFactory | None = None,
) -> list[StructuredTool]:
    if session_factory is None:
        from app.db.session import AsyncSessionLocal

        session_factory = AsyncSessionLocal

    return [
        StructuredTool.from_function(
            coroutine=_search_documents_tool(user, session_factory),
            name="search_documents",
            description=(
                "Search authoritative ParcelPilot documentation. Use this for support policies, SLA rules, "
                "cancellation rules, service credits, plan capabilities, product issues, or customer-specific "
                "contract terms. Do not use this for order or ticket records."
            ),
            args_schema=SearchDocumentsInput,
        )
    ]


def _search_documents_tool(user: UserContext, session_factory: SessionFactory):
    async def search_documents(query: str, domain: str | None = None) -> dict[str, Any]:
        async with session_factory() as session:
            result = await DocumentSearchService(session).search(query=query, domain=domain, user=user)
            return result.model_dump(mode="json")

    return search_documents
