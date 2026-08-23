"""LangChain write tools for escalation actions."""
from collections.abc import Callable
from typing import Any

from langchain_core.tools import StructuredTool
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.auth import UserContext
from app.schemas.tools import CreateEscalationInput
from app.services.escalations import EscalationService


SessionFactory = Callable[[], AsyncSession]


def create_escalation_tools(
    user: UserContext,
    session_factory: SessionFactory | None = None,
) -> list[StructuredTool]:
    if session_factory is None:
        from app.db.session import AsyncSessionLocal

        session_factory = AsyncSessionLocal

    return [
        StructuredTool.from_function(
            coroutine=_create_escalation_tool(user, session_factory),
            name="create_escalation",
            description=(
                "Create a support escalation for an accessible ticket. This is a state-changing action and must only "
                "execute after explicit human approval. Re-checks authorization at execution time."
            ),
            args_schema=CreateEscalationInput,
        )
    ]


def _create_escalation_tool(user: UserContext, session_factory: SessionFactory):
    async def create_escalation(ticket_id: str, priority: str, reason: str) -> dict[str, Any]:
        request = CreateEscalationInput(ticket_id=ticket_id, priority=priority, reason=reason)
        async with session_factory() as session:
            async with session.begin():
                result = await EscalationService(session).execute_create_escalation(
                    request=request,
                    user=user,
                    thread_id="langgraph",
                    idempotency_key=f"{user.user_id}:{ticket_id}:{priority}:{reason}",
                )
            return result.model_dump(mode="json")

    return create_escalation
