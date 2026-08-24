"""LangChain document search tool backed by authorized retrieval."""
from collections.abc import Callable
from typing import Annotated, Any

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import StructuredTool
from langchain_core.tools.base import InjectedToolArg
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.tools import SearchDocumentsInput
from app.services.document_search import DocumentSearchService


SessionFactory = Callable[[], AsyncSession]


def create_document_search_tools(
    session_factory: SessionFactory | None = None,
) -> list[StructuredTool]:
    if session_factory is None:
        from app.db.session import AsyncSessionLocal

        session_factory = AsyncSessionLocal

    return [
        StructuredTool.from_function(
            coroutine=_search_documents_tool(session_factory),
            name="search_documents",
            description=(
                "Search authoritative ParcelPilot documentation. Use this for support policies, SLA rules, "
                "cancellation rules, service credits, plan capabilities, product issues, or customer-specific "
                "contract terms. Do not use this for order or ticket records."
            ),
            args_schema=SearchDocumentsInput,
        )
    ]


def _search_documents_tool(session_factory: SessionFactory):
    async def search_documents(
        query: str,
        domain: str | None = None,
        config: Annotated[RunnableConfig, InjectedToolArg] = None,
    ) -> dict[str, Any]:
        from app.schemas.auth import UserContext

        user: UserContext = (config or {}).get("configurable", {}).get("user")
        if user is None:
            return {"success": False, "error": "Missing user context"}
        async with session_factory() as session:
            result = await DocumentSearchService(session).search(query=query, domain=domain, user=user)
            return result.model_dump(mode="json")

    return search_documents
