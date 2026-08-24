"""LangChain write tools for escalation actions."""
from collections.abc import Callable
from typing import Annotated, Any

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import StructuredTool
from langchain_core.tools.base import InjectedToolArg
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.tools import CreateEscalationInput
from app.services.escalations import EscalationService


SessionFactory = Callable[[], AsyncSession]


def create_escalation_tools(
    session_factory: SessionFactory | None = None,
) -> list[StructuredTool]:
    if session_factory is None:
        from app.db.session import AsyncSessionLocal

        session_factory = AsyncSessionLocal

    return [
        StructuredTool.from_function(
            coroutine=_create_escalation_tool(session_factory),
            name="create_escalation",
            description=(
                "Create a support escalation for an accessible ticket. This is a state-changing action and must only "
                "execute after explicit human approval. Re-checks authorization at execution time."
            ),
            args_schema=CreateEscalationInput,
        )
    ]


def _create_escalation_tool(session_factory: SessionFactory):
    async def create_escalation(
        ticket_id: str,
        priority: str,
        reason: str,
        config: Annotated[RunnableConfig, InjectedToolArg] = None,
    ) -> dict[str, Any]:
        from app.schemas.auth import UserContext
        from langgraph.types import interrupt

        configurable = (config or {}).get("configurable", {})
        user: UserContext = configurable.get("user")
        thread_id: str = configurable.get("thread_id", "langgraph")

        if user is None:
            return {"success": False, "error": "Missing user context"}

        request = CreateEscalationInput(ticket_id=ticket_id, priority=priority, reason=reason)
        async with session_factory() as session:
            async with session.begin():
                pending = await EscalationService(session).propose_create_escalation(
                    request=request,
                    user=user,
                    thread_id=thread_id,
                )

            if not pending.success:
                return pending.model_dump(mode="json")

            # Pause LangGraph agent execution and require human approval
            interrupt({
                "action_id": str(pending.action_id),
                "action": "create_escalation",
                "ticket_id": request.ticket_id,
                "priority": request.priority,
                "reason": request.reason,
            })

            return pending.model_dump(mode="json")

    return create_escalation

