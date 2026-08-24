"""State-changing escalation workflow with human approval and audit events."""
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Escalation, PendingAction
from app.repositories import AuditEventRepository, EscalationRepository, PendingActionRepository, TicketRepository
from app.schemas.auth import UserContext
from app.schemas.tools import (
    CreateEscalationInput,
    EscalationAction,
    EscalationResult,
    PendingActionResult,
    ToolError,
)
from app.security.authorization import AuthorizationError
from app.security.authorization import require_permission


CREATE_ESCALATION_TOOL = "create_escalation"


class EscalationService:
    def __init__(self, session: AsyncSession) -> None:
        self.audit_events = AuditEventRepository(session)
        self.escalations = EscalationRepository(session)
        self.pending_actions = PendingActionRepository(session)
        self.tickets = TicketRepository(session)

    async def propose_create_escalation(
        self,
        *,
        request: CreateEscalationInput,
        user: UserContext,
        thread_id: str,
        action_id: UUID | None = None,
    ) -> PendingActionResult:
        require_permission(user, "escalations:create")
        ticket = await self.tickets.get_accessible(request.ticket_id, user)
        if ticket is None:
            return _pending_error(
                thread_id=thread_id,
                action_id=action_id or uuid4(),
                request=request,
                code="NOT_FOUND",
                message="No accessible ticket was found.",
            )

        now = _now()
        action = PendingAction(
            action_id=action_id or uuid4(),
            thread_id=thread_id,
            tool_name=CREATE_ESCALATION_TOOL,
            status="pending",
            user_id=user.user_id,
            account_id=ticket.account_id,
            arguments=request.model_dump(mode="json"),
            result=None,
            created_at=now,
            updated_at=now,
        )
        await self.pending_actions.save(action)
        await self._audit(
            event_type="ESCALATION_PROPOSED",
            user=user,
            account_id=ticket.account_id,
            thread_id=thread_id,
            ticket_id=ticket.id,
            payload={"action_id": str(action.action_id), "arguments": action.arguments},
            created_at=now,
        )

        return PendingActionResult(
            success=True,
            type="approval_required",
            thread_id=thread_id,
            action_id=action.action_id,
            action=_action_from_input(request),
            message="Escalation approval is required before execution.",
        )

    async def approve_action(self, *, action_id: UUID, user: UserContext) -> PendingActionResult:
        action = await self.pending_actions.get(action_id)
        if action is None:
            return _missing_action(action_id)

        request = CreateEscalationInput(**action.arguments)
        if action.status == "rejected":
            return PendingActionResult(
                success=False,
                type="rejected",
                thread_id=action.thread_id,
                action_id=action.action_id,
                action=_action_from_input(request),
                message="The escalation action was previously rejected.",
                error=ToolError(code="INVALID_ID", message="The action was already rejected."),
            )

        existing = await self.escalations.get_by_idempotency_key(str(action.action_id))
        if action.status == "executed" or existing is not None:
            if existing is not None:
                result = _escalation_result(existing, "Escalation was already created.")
            elif action.result:
                result = EscalationResult(**action.result)
            else:
                result = EscalationResult(success=True, created=True, message="Escalation was already created.")

            action.status = "executed"
            action.result = result.model_dump(mode="json")
            action.updated_at = _now()
            return PendingActionResult(
                success=True,
                type="executed",
                thread_id=action.thread_id,
                action_id=action.action_id,
                action=_action_from_input(request),
                message="Escalation was already created.",
                escalation=result,
            )

        now = _now()
        await self._audit(
            event_type="ESCALATION_APPROVED",
            user=user,
            account_id=action.account_id,
            thread_id=action.thread_id,
            ticket_id=request.ticket_id,
            payload={"action_id": str(action.action_id)},
            created_at=now,
        )

        try:
            escalation_result = await self.execute_create_escalation(
                request=request,
                user=user,
                thread_id=action.thread_id,
                idempotency_key=str(action.action_id),
            )
        except AuthorizationError:
            escalation_result = EscalationResult(
                success=False,
                created=False,
                message="The authenticated user is no longer authorized to create this escalation.",
                error=ToolError(
                    code="FORBIDDEN",
                    message="The authenticated user is no longer authorized to create this escalation.",
                ),
            )
        action.status = "executed" if escalation_result.success else "pending"
        action.result = escalation_result.model_dump(mode="json")
        action.updated_at = _now()

        return PendingActionResult(
            success=escalation_result.success,
            type="executed" if escalation_result.success else "approval_required",
            thread_id=action.thread_id,
            action_id=action.action_id,
            action=_action_from_input(request),
            message=escalation_result.message,
            escalation=escalation_result,
            error=escalation_result.error,
        )

    async def reject_action(self, *, action_id: UUID, user: UserContext) -> PendingActionResult:
        action = await self.pending_actions.get(action_id)
        if action is None:
            return _missing_action(action_id)

        request = CreateEscalationInput(**action.arguments)
        if action.status == "executed":
            return PendingActionResult(
                success=False,
                type="executed",
                thread_id=action.thread_id,
                action_id=action.action_id,
                action=_action_from_input(request),
                message="The escalation action has already executed and cannot be rejected.",
                error=ToolError(code="INVALID_ID", message="The action was already executed."),
            )

        if action.status == "rejected":
            return PendingActionResult(
                success=True,
                type="rejected",
                thread_id=action.thread_id,
                action_id=action.action_id,
                action=_action_from_input(request),
                message="The escalation was not created.",
            )

        now = _now()
        action.status = "rejected"
        action.updated_at = now
        await self._audit(
            event_type="ESCALATION_REJECTED",
            user=user,
            account_id=action.account_id,
            thread_id=action.thread_id,
            ticket_id=request.ticket_id,
            payload={"action_id": str(action.action_id)},
            created_at=now,
        )

        return PendingActionResult(
            success=True,
            type="rejected",
            thread_id=action.thread_id,
            action_id=action.action_id,
            action=_action_from_input(request),
            message="The escalation was not created.",
        )

    async def execute_create_escalation(
        self,
        *,
        request: CreateEscalationInput,
        user: UserContext,
        thread_id: str,
        idempotency_key: str,
    ) -> EscalationResult:
        require_permission(user, "escalations:create")
        ticket = await self.tickets.get_accessible(request.ticket_id, user)
        if ticket is None:
            return EscalationResult(
                success=False,
                created=False,
                message="No accessible ticket was found.",
                error=ToolError(code="NOT_FOUND", message="No accessible ticket was found."),
            )

        existing = await self.escalations.get_by_idempotency_key(idempotency_key)
        if existing is not None:
            return _escalation_result(existing, "Escalation was already created.")

        now = _now()
        escalation = Escalation(
            account_id=ticket.account_id,
            ticket_id=ticket.id,
            priority=request.priority,
            reason=request.reason,
            status="open",
            created_by=user.user_id,
            created_at=now,
            idempotency_key=idempotency_key,
        )
        await self.escalations.create_authorized(escalation, user)
        await self._audit(
            event_type="ESCALATION_CREATED",
            user=user,
            account_id=ticket.account_id,
            thread_id=thread_id,
            ticket_id=ticket.id,
            payload={
                "escalation_id": str(escalation.id),
                "priority": escalation.priority,
                "reason": escalation.reason,
                "idempotency_key": idempotency_key,
            },
            created_at=now,
        )
        return _escalation_result(escalation, "Escalation created.")

    async def _audit(
        self,
        *,
        event_type: str,
        user: UserContext,
        account_id: str | None,
        thread_id: str,
        ticket_id: str,
        payload: dict,
        created_at: datetime,
    ) -> None:
        await self.audit_events.record(
            event_type=event_type,
            user_id=user.user_id,
            account_id=account_id,
            thread_id=thread_id,
            resource_type="ticket",
            resource_id=ticket_id,
            tool_name=CREATE_ESCALATION_TOOL,
            payload=payload,
            created_at=created_at,
        )


def _action_from_input(request: CreateEscalationInput) -> EscalationAction:
    return EscalationAction(tool=CREATE_ESCALATION_TOOL, arguments=request)


def _escalation_result(escalation: Escalation, message: str) -> EscalationResult:
    return EscalationResult(
        success=True,
        created=True,
        escalation_id=escalation.id,
        ticket_id=escalation.ticket_id,
        priority=escalation.priority,
        status=escalation.status,
        message=message,
    )


def _pending_error(
    *,
    thread_id: str,
    action_id: UUID,
    request: CreateEscalationInput,
    code: str,
    message: str,
) -> PendingActionResult:
    return PendingActionResult(
        success=False,
        type="approval_required",
        thread_id=thread_id,
        action_id=action_id,
        action=_action_from_input(request),
        message=message,
        error=ToolError(code=code, message=message),
    )


def _missing_action(action_id: UUID) -> PendingActionResult:
    return PendingActionResult(
        success=False,
        type="approval_required",
        thread_id="",
        action_id=action_id,
        action=_action_from_input(CreateEscalationInput(ticket_id="", priority="normal", reason="")),
        message="No pending action was found.",
        error=ToolError(code="NOT_FOUND", message="No pending action was found."),
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)
