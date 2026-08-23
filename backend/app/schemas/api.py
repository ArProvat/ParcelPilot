"""Public API request and response schemas."""
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ChatRequest(BaseModel):
    thread_id: str
    message: str


class DecisionRequest(BaseModel):
    action_id: UUID
    decision: Literal["approve", "reject"]


class MockLoginRequest(BaseModel):
    user: Literal["northstar", "lumenworks", "admin"] = "northstar"


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class StreamEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: str
    event_id: str
    thread_id: str
    timestamp: datetime
    data: dict
