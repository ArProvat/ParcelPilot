"""LangChain tools for deterministic business-rule evaluations."""
from collections.abc import Callable
from typing import Any

from langchain_core.tools import StructuredTool
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.auth import UserContext
from app.schemas.tools import EvaluateOrderInput, EvaluateTicketInput
from app.services.business_rules import BusinessRuleService


SessionFactory = Callable[[], AsyncSession]


def create_business_rule_tools(
    user: UserContext,
    session_factory: SessionFactory | None = None,
) -> list[StructuredTool]:
    if session_factory is None:
        from app.db.session import AsyncSessionLocal

        session_factory = AsyncSessionLocal

    return [
        StructuredTool.from_function(
            coroutine=_evaluate_cancellation_tool(user, session_factory),
            name="evaluate_cancellation",
            description=(
                "Deterministically evaluate whether an accessible order can be cancelled and what cancellation fee applies. "
                "Use this for cancellation eligibility decisions; it applies customer agreement overrides and the current SOP."
            ),
            args_schema=EvaluateOrderInput,
        ),
        StructuredTool.from_function(
            coroutine=_evaluate_service_credit_tool(user, session_factory),
            name="evaluate_service_credit",
            description=(
                "Deterministically evaluate failed-pickup service credit eligibility and amount for an accessible order. "
                "Use this for service-credit decisions; it applies customer-specific overrides and the current SOP."
            ),
            args_schema=EvaluateOrderInput,
        ),
        StructuredTool.from_function(
            coroutine=_evaluate_ticket_sla_tool(user, session_factory),
            name="evaluate_ticket_sla",
            description=(
                "Deterministically evaluate support-ticket severity, response target, breach status, and escalation need."
            ),
            args_schema=EvaluateTicketInput,
        ),
    ]


def _evaluate_cancellation_tool(user: UserContext, session_factory: SessionFactory):
    async def evaluate_cancellation(order_id: str) -> dict[str, Any]:
        async with session_factory() as session:
            result = await BusinessRuleService(session).evaluate_cancellation(order_id, user)
            return result.model_dump(mode="json")

    return evaluate_cancellation


def _evaluate_service_credit_tool(user: UserContext, session_factory: SessionFactory):
    async def evaluate_service_credit(order_id: str) -> dict[str, Any]:
        async with session_factory() as session:
            result = await BusinessRuleService(session).evaluate_service_credit(order_id, user)
            return result.model_dump(mode="json")

    return evaluate_service_credit


def _evaluate_ticket_sla_tool(user: UserContext, session_factory: SessionFactory):
    async def evaluate_ticket_sla(ticket_id: str) -> dict[str, Any]:
        async with session_factory() as session:
            result = await BusinessRuleService(session).evaluate_ticket_sla(ticket_id, user)
            return result.model_dump(mode="json")

    return evaluate_ticket_sla
