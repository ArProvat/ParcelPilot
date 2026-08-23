"""Application streaming protocol helpers."""
from datetime import datetime, timezone
import json
from uuid import uuid4

from app.schemas.api import StreamEvent


def make_event(thread_id: str, event_type: str, data: dict) -> StreamEvent:
    return StreamEvent(
        type=event_type,
        event_id=str(uuid4()),
        thread_id=thread_id,
        timestamp=datetime.now(timezone.utc),
        data=data,
    )


def serialize_sse(event: StreamEvent) -> str:
    data = event.model_dump(mode="json")
    return f"event: {event.type}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"
