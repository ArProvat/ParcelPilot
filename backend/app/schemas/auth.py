"""Authenticated caller context used by data and retrieval layers."""
from pydantic import BaseModel, ConfigDict


class UserContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    user_id: str
    role: str
    account_id: str | None = None
