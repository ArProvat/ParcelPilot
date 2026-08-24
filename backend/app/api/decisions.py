"""Human approval decision endpoints with full re-authorization."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependency import get_db_session
from app.repositories import ConversationThreadRepository, PendingActionRepository
from app.schemas.api import DecisionRequest
from app.schemas.auth import UserContext
from app.security.auth import get_current_user
from app.services.escalations import EscalationService


router = APIRouter()


@router.post("/{thread_id}/decisions")
async def decide(
    thread_id: str,
    request: DecisionRequest,
    user: UserContext = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Resume / resolve a pending human-in-the-loop action.

    Security pipeline:
      1. Verify authenticated user identity (UserContext from JWT/token)
      2. Verify thread access for this user
      3. Verify pending action ownership (tenant boundary)
      4. Re-authorize tool execution at resume time (permission + resource scope)
    """
    # 1. Thread access check
    thread = await ConversationThreadRepository(session).get_for_user(thread_id, user)
    if thread is None:
        raise HTTPException(status_code=404, detail="Thread not found")

    # 2. Pending action lookup and ownership check
    action = await PendingActionRepository(session).get(request.action_id)
    if action is None or action.thread_id != thread_id:
        raise HTTPException(status_code=404, detail="Pending action not found")

    if user.role != "operations_admin" and action.account_id != user.account_id:
        raise HTTPException(status_code=403, detail="Not authorized to decide actions for this account")

    # 3. Re-authorize & execute or reject
    service = EscalationService(session)
    if request.decision == "approve":
        result = await service.approve_action(action_id=request.action_id, user=user)
        if not result.success and result.error and result.error.code == "FORBIDDEN":
            await session.commit()
            raise HTTPException(
                status_code=403,
                detail=result.error.message or "User is not authorized to execute this escalation",
            )
    else:
        result = await service.reject_action(action_id=request.action_id, user=user)

    await session.commit()
    event_type = "action.completed" if result.type == "executed" else "action.rejected"
    return {
        "type": event_type,
        "thread_id": thread_id,
        "action_id": str(request.action_id),
        "result": result.model_dump(mode="json"),
    }
