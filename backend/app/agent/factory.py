"""LangGraph agent assembly for ParcelPilot."""
from collections.abc import Callable

from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.prompt import SYSTEM_PROMPT
from app.schemas.auth import UserContext
from app.tools import create_agent_tools


SessionFactory = Callable[[], AsyncSession]


def create_parcelpilot_agent(
    model,
    user: UserContext,
    session_factory: SessionFactory | None = None,
    *,
    checkpointer=None,
    enable_human_approval: bool = True,
):
    """Create an agent with safe, user-scoped ParcelPilot tools."""
    middleware = []
    if enable_human_approval:
        middleware.append(
            HumanInTheLoopMiddleware(
                interrupt_on={
                    "create_escalation": {
                        "allowed_decisions": ["approve", "reject"],
                    }
                }
            )
        )

    return create_agent(
        model=model,
        tools=create_agent_tools(user, session_factory=session_factory),
        system_prompt=SYSTEM_PROMPT,
        middleware=middleware,
        context_schema=UserContext,
        checkpointer=checkpointer,
    )
