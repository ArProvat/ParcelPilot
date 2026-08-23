"""Human approval decision endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependency import get_db_session
from app.repositories import PendingActionRepository
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
    action = await PendingActionRepository(session).get(request.action_id)
    if action is None or action.thread_id != thread_id:
        raise HTTPException(status_code=404, detail="Pending action not found")

    service = EscalationService(session)
    if request.decision == "approve":
        result = await service.approve_action(action_id=request.action_id, user=user)
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
