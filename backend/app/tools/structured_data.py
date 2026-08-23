"""LangChain structured-data tools backed by authorized domain services."""
from collections.abc import Callable
from typing import Any

from langchain_core.tools import StructuredTool
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.auth import UserContext
from app.schemas.tools import GetOrderInput, GetTicketInput, ListAccountTicketsInput
from app.services.operational_data import OperationalDataService


SessionFactory = Callable[[], AsyncSession]


def create_structured_data_tools(
    user: UserContext,
    session_factory: SessionFactory | None = None,
) -> list[StructuredTool]:
    if session_factory is None:
        from app.db.session import AsyncSessionLocal

        session_factory = AsyncSessionLocal

    return [
        StructuredTool.from_function(
            coroutine=_get_order_tool(user, session_factory),
            name="get_order",
            description="Look up accessible operational facts for one order by order_id.",
            args_schema=GetOrderInput,
        ),
        StructuredTool.from_function(
            coroutine=_get_ticket_tool(user, session_factory),
            name="get_ticket",
            description="Look up an accessible support ticket by ticket_id.",
            args_schema=GetTicketInput,
        ),
        StructuredTool.from_function(
            coroutine=_get_my_account_tool(user, session_factory),
            name="get_my_account",
            description="Look up the authenticated customer's own account.",
        ),
        StructuredTool.from_function(
            coroutine=_list_account_tickets_tool(user, session_factory),
            name="list_account_tickets",
            description="List accessible account tickets using status open, closed, or all.",
            args_schema=ListAccountTicketsInput,
        ),
    ]


def _get_order_tool(user: UserContext, session_factory: SessionFactory):
    async def get_order(order_id: str) -> dict[str, Any]:
        async with session_factory() as session:
            result = await OperationalDataService(session).get_visible_order(order_id, user)
            return result.model_dump(mode="json")

    return get_order


def _get_ticket_tool(user: UserContext, session_factory: SessionFactory):
    async def get_ticket(ticket_id: str) -> dict[str, Any]:
        async with session_factory() as session:
            result = await OperationalDataService(session).get_visible_ticket(ticket_id, user)
            return result.model_dump(mode="json")

    return get_ticket


def _get_my_account_tool(user: UserContext, session_factory: SessionFactory):
    async def get_my_account() -> dict[str, Any]:
        async with session_factory() as session:
            result = await OperationalDataService(session).get_my_account(user)
            return result.model_dump(mode="json")

    return get_my_account


def _list_account_tickets_tool(user: UserContext, session_factory: SessionFactory):
    async def list_account_tickets(status: str = "open") -> dict[str, Any]:
        async with session_factory() as session:
            result = await OperationalDataService(session).list_account_tickets(status, user)
            return result.model_dump(mode="json")

    return list_account_tickets
