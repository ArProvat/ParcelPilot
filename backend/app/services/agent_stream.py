"""Agent-facing stream service that maps internal work to app events."""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ConversationMessage, ConversationThread
from app.repositories import ConversationMessageRepository, ConversationThreadRepository
from app.schemas.api import StreamEvent
from app.schemas.auth import UserContext
from app.schemas.tools import CreateEscalationInput
from app.services.business_rules import BusinessRuleService
from app.services.document_search import DocumentSearchService
from app.services.escalations import EscalationService
from app.services.operational_data import OperationalDataService
from app.services.streaming import make_event


class AgentStreamService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.messages = ConversationMessageRepository(session)
        self.threads = ConversationThreadRepository(session)

    async def stream_chat(
        self,
        *,
        thread_id: str,
        message: str,
        user: UserContext,
    ):
        thread = await self._ensure_thread(thread_id, user)
        await self._save_message(thread.id, "user", message)
        await self.session.commit()

        yield make_event(thread_id, "message.started", {"message_id": str(uuid4())})

        lower = message.lower()
        if "escalate" in lower and "tkt-501" in lower:
            async for event in self._stream_escalation_flow(thread_id, user):
                yield event
        elif "cancel" in lower and "ord-" in lower:
            async for event in self._stream_cancellation_flow(thread_id, message, user):
                yield event
        else:
            text = "I can help with orders, tickets, policies, service credits, SLA checks, and escalation requests."
            yield make_event(thread_id, "message.delta", {"text": text})
            await self._save_message(thread_id, "assistant", text)
            await self.session.commit()

        yield make_event(thread_id, "message.completed", {"message_id": str(uuid4())})

    async def _stream_cancellation_flow(self, thread_id: str, message: str, user: UserContext):
        order_id = _extract_id(message, "ORD-") or ""

        yield make_event(thread_id, "tool.started", {"tool_call_id": str(uuid4()), "tool": "get_order", "label": f"Looking up {order_id}"})
        order_result = await OperationalDataService(self.session).get_visible_order(order_id, user)
        yield make_event(thread_id, "tool.completed", {"tool": "get_order", "status": "success" if order_result.success else "not_found"})

        yield make_event(thread_id, "tool.started", {"tool_call_id": str(uuid4()), "tool": "evaluate_cancellation", "label": "Calculating cancellation eligibility"})
        decision = await BusinessRuleService(self.session).evaluate_cancellation(order_id, user)
        yield make_event(
            thread_id,
            "decision.completed",
            {
                "decision": "cancellation_allowed" if decision.allowed else "cancellation_not_allowed",
                "fee_inr": str(decision.fee_inr) if decision.fee_inr is not None else None,
                "reason_code": decision.reason_code,
            },
        )

        yield make_event(thread_id, "tool.started", {"tool_call_id": str(uuid4()), "tool": "search_documents", "label": "Checking cancellation rules"})
        docs = await DocumentSearchService(self.session).search(
            query="Northstar cancellation terms for booked shipment",
            domain="cancellation",
            user=user,
        )
        for item in docs.evidence[:3]:
            yield make_event(
                thread_id,
                "source.retrieved",
                {"source": item.source_name, "section": item.section, "page": item.page},
            )
        yield make_event(thread_id, "tool.completed", {"tool": "search_documents", "status": "success"})

        text = decision.explanation
        yield make_event(thread_id, "message.delta", {"text": text})
        await self._save_message(thread_id, "assistant", text)
        await self.session.commit()

    async def _stream_escalation_flow(self, thread_id: str, user: UserContext):
        yield make_event(thread_id, "tool.started", {"tool_call_id": str(uuid4()), "tool": "get_ticket", "label": "Looking up TKT-501"})
        ticket = await OperationalDataService(self.session).get_visible_ticket("TKT-501", user)
        yield make_event(thread_id, "tool.completed", {"tool": "get_ticket", "status": "success" if ticket.success else "not_found"})

        yield make_event(thread_id, "tool.started", {"tool_call_id": str(uuid4()), "tool": "evaluate_ticket_sla", "label": "Checking SLA"})
        sla = await BusinessRuleService(self.session).evaluate_ticket_sla("TKT-501", user)
        yield make_event(
            thread_id,
            "decision.completed",
            {
                "decision": "sla_breached" if sla.breached else "sla_not_breached",
                "severity": sla.severity,
                "breach_minutes": sla.breach_minutes,
                "requires_immediate_escalation": sla.requires_immediate_escalation,
            },
        )

        if sla.requires_immediate_escalation:
            request = CreateEscalationInput(
                ticket_id="TKT-501",
                priority="urgent",
                reason="P1 shipment creation outage with breached first-response SLA.",
            )
            action = await EscalationService(self.session).propose_create_escalation(
                request=request,
                user=user,
                thread_id=thread_id,
            )
            await self.session.commit()
            yield make_event(
                thread_id,
                "approval.required",
                {
                    "action_id": str(action.action_id),
                    "action": action.action.tool,
                    "ticket_id": action.action.arguments.ticket_id,
                    "priority": action.action.arguments.priority,
                    "reason": action.action.arguments.reason,
                },
            )
            text = "Escalation is recommended and requires approval before it is created."
        else:
            text = "Escalation is not required based on the current SLA evaluation."

        yield make_event(thread_id, "message.delta", {"text": text})
        await self._save_message(thread_id, "assistant", text)
        await self.session.commit()

    async def _ensure_thread(self, thread_id: str, user: UserContext) -> ConversationThread:
        thread = await self.threads.get_for_user(thread_id, user)
        if thread is not None:
            return thread

        now = datetime.now(timezone.utc)
        thread = ConversationThread(
            id=thread_id,
            user_id=user.user_id,
            account_id=user.account_id,
            title=None,
            created_at=now,
            updated_at=now,
        )
        await self.threads.save(thread)
        return thread

    async def _save_message(self, thread_id: str, role: str, content: str) -> None:
        await self.messages.save(
            ConversationMessage(
                thread_id=thread_id,
                role=role,
                content=content,
                metadata_={},
                created_at=datetime.now(timezone.utc),
            )
        )


def _extract_id(text: str, prefix: str) -> str | None:
    upper = text.upper()
    start = upper.find(prefix)
    if start == -1:
        return None
    end = start
    while end < len(upper) and (upper[end].isalnum() or upper[end] == "-"):
        end += 1
    return upper[start:end]
