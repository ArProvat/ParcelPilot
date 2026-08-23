"""Evidence objects returned by authority-aware document retrieval."""
from pydantic import BaseModel, ConfigDict


class Evidence(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_id: str
    source_name: str
    source_type: str
    section: str | None = None
    page: int | None = None
    authority_class: str
    status: str
    account_id: str | None = None
    content: str
    relevance_score: float | None = None
