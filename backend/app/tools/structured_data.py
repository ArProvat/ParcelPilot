"""LangChain structured-data tools backed by authorized domain services."""
from collections.abc import Callable
from typing import Annotated, Any

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import StructuredTool
from langchain_core.tools.base import InjectedToolArg
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.tools import GetOrderInput, GetTicketInput, ListAccountTicketsInput
from app.services.operational_data import OperationalDataService


SessionFactory = Callable[[], AsyncSession]


def create_structured_data_tools(
    session_factory: SessionFactory | None = None,
) -> list[StructuredTool]:
    if session_factory is None:
        from app.db.session import AsyncSessionLocal

        session_factory = AsyncSessionLocal

    return [
        StructuredTool.from_function(
            coroutine=_get_order_tool(session_factory),
            name="get_order",
            description=(
                "Retrieve operational facts about a shipment/order. Use this for shipment status, booking time, "
                "pickup window, pickup confirmation, shipment fee, cancellation request, carrier fault, or "
                "customer fault. This tool does not determine policy eligibility."
            ),
            args_schema=GetOrderInput,
        ),
        StructuredTool.from_function(
            coroutine=_get_ticket_tool(session_factory),
            name="get_ticket",
            description=(
                "Retrieve an accessible support ticket by ticket_id. Historical resolutions are returned only "
                "as context and must not override current policy, SOPs, or signed agreements."
            ),
            args_schema=GetTicketInput,
        ),
        StructuredTool.from_function(
            coroutine=_get_my_account_tool(session_factory),
            name="get_my_account",
            description="Retrieve the authenticated customer's own account profile and plan facts.",
        ),
        StructuredTool.from_function(
            coroutine=_list_account_tickets_tool(session_factory),
            name="list_account_tickets",
            description="List tickets accessible to the authenticated user using status open, closed, or all.",
            args_schema=ListAccountTicketsInput,
        ),
    ]


def _get_order_tool(session_factory: SessionFactory):
    async def get_order(order_id: str, config: Annotated[RunnableConfig, InjectedToolArg] = None) -> dict[str, Any]:
        from app.schemas.auth import UserContext

        user: UserContext = (config or {}).get("configurable", {}).get("user")
        if user is None:
            return {"success": False, "error": "Missing user context"}
        async with session_factory() as session:
            result = await OperationalDataService(session).get_visible_order(order_id, user)
            return result.model_dump(mode="json")

    return get_order


def _get_ticket_tool(session_factory: SessionFactory):
    async def get_ticket(ticket_id: str, config: Annotated[RunnableConfig, InjectedToolArg] = None) -> dict[str, Any]:
        from app.schemas.auth import UserContext

        user: UserContext = (config or {}).get("configurable", {}).get("user")
        if user is None:
            return {"success": False, "error": "Missing user context"}
        async with session_factory() as session:
            result = await OperationalDataService(session).get_visible_ticket(ticket_id, user)
            return result.model_dump(mode="json")

    return get_ticket


def _get_my_account_tool(session_factory: SessionFactory):
    async def get_my_account(config: Annotated[RunnableConfig, InjectedToolArg] = None) -> dict[str, Any]:
        from app.schemas.auth import UserContext

        user: UserContext = (config or {}).get("configurable", {}).get("user")
        if user is None:
            return {"success": False, "error": "Missing user context"}
        async with session_factory() as session:
            result = await OperationalDataService(session).get_my_account(user)
            return result.model_dump(mode="json")

    return get_my_account


def _list_account_tickets_tool(session_factory: SessionFactory):
    async def list_account_tickets(
        status: str = "open",
        config: Annotated[RunnableConfig, InjectedToolArg] = None,
    ) -> dict[str, Any]:
        from app.schemas.auth import UserContext

        user: UserContext = (config or {}).get("configurable", {}).get("user")
        if user is None:
            return {"success": False, "error": "Missing user context"}
        async with session_factory() as session:
            result = await OperationalDataService(session).list_account_tickets(status, user)
            return result.model_dump(mode="json")

    return list_account_tickets
