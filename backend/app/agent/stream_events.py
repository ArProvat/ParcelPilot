"""LangGraph → ParcelPilot SSE event translator.

This module owns the boundary between LangGraph's internal streaming protocol
and the application's public SSE event schema.  Nothing outside this module
should inspect raw LangGraph message objects for the purpose of producing
frontend events.

Stream mode mapping
───────────────────
LangGraph ``stream_mode="messages"``  →  token-by-token AI text deltas and
    tool-call metadata emitted as the model generates them.

LangGraph ``stream_mode="updates"``   →  node-level state snapshots after
    each graph step; used to detect tool results and graph interrupts.

Public event types (matches existing ``make_event`` / ``serialize_sse`` layer)
───────────────────────────────────────────────────────────────────────────────
  message.delta        – streaming text token from the LLM
  tool.started         – LLM chose to call a tool
  tool.completed       – tool returned a result
  source.retrieved     – a document evidence item from search_documents
  approval.required    – graph interrupted for human approval
  decision.completed   – evaluate_* tool produced a structured decision
"""
from __future__ import annotations

import logging
from typing import Any

from app.schemas.api import StreamEvent
from app.services.streaming import make_event

logger = logging.getLogger(__name__)

# Tool names whose results contain structured decision fields we surface.
_DECISION_TOOLS = {"evaluate_cancellation", "evaluate_service_credit", "evaluate_ticket_sla"}

# Tool names whose results may contain source evidence.
_SEARCH_TOOLS = {"search_documents"}


class AgentEventTranslator:
    """Translates raw LangGraph stream items into ParcelPilot ``StreamEvent``s.

    Usage::

        translator = AgentEventTranslator()
        async for mode, payload in agent.astream(..., stream_mode=[...]):
            for event in translator.translate(mode, payload, thread_id):
                yield event
    """

    def translate(
        self,
        mode: str,
        payload: Any,
        thread_id: str,
    ) -> list[StreamEvent]:
        """Translate one LangGraph stream item into zero or more StreamEvents."""
        try:
            if mode == "messages":
                return self._handle_messages_chunk(payload, thread_id)
            if mode == "updates":
                return self._handle_updates(payload, thread_id)
        except Exception:
            logger.exception("event_translation_failed", extra={"mode": mode})
        return []

    # ------------------------------------------------------------------
    # messages mode  (token-level streaming)
    # ------------------------------------------------------------------

    def _handle_messages_chunk(self, payload: Any, thread_id: str) -> list[StreamEvent]:
        """Handle a (message_chunk, metadata) tuple from stream_mode='messages'."""
        events: list[StreamEvent] = []

        # LangGraph yields (AIMessageChunk | ToolMessage, metadata) tuples.
        if not isinstance(payload, (list, tuple)) or len(payload) != 2:
            return events

        chunk, _meta = payload

        chunk_type = type(chunk).__name__

        if chunk_type == "AIMessageChunk":
            # Text delta
            content = chunk.content if isinstance(chunk.content, str) else ""
            if content:
                events.append(make_event(thread_id, "message.delta", {"text": content}))

            # Tool call deltas – announce tool.started when we get a complete call
            for tc in getattr(chunk, "tool_calls", []):
                if tc.get("name"):
                    events.append(
                        make_event(
                            thread_id,
                            "tool.started",
                            {
                                "tool_call_id": tc.get("id", ""),
                                "tool": tc["name"],
                                "label": _tool_label(tc["name"]),
                            },
                        )
                    )

        elif chunk_type == "ToolMessage":
            events.extend(self._tool_message_events(chunk, thread_id))

        return events

    # ------------------------------------------------------------------
    # updates mode  (node-level state snapshots)
    # ------------------------------------------------------------------

    def _handle_updates(self, payload: Any, thread_id: str) -> list[StreamEvent]:
        """Handle a node-update dict from stream_mode='updates'."""
        events: list[StreamEvent] = []

        # payload is {node_name: state_delta}
        if not isinstance(payload, dict):
            return events

        for node_name, state in payload.items():
            if node_name == "__interrupt__":
                # LangGraph HITL interrupt – surface as approval.required
                interrupt_value = state[0] if isinstance(state, (list, tuple)) and state else state
                events.extend(self._interrupt_events(interrupt_value, thread_id))
                continue

            messages = state.get("messages", []) if isinstance(state, dict) else []
            for msg in messages:
                msg_type = type(msg).__name__
                if msg_type == "AIMessage":
                    # Completed AI turn – emit tool.started for any tool calls
                    # not yet emitted via the messages stream
                    for tc in getattr(msg, "tool_calls", []):
                        if tc.get("name"):
                            events.append(
                                make_event(
                                    thread_id,
                                    "tool.started",
                                    {
                                        "tool_call_id": tc.get("id", ""),
                                        "tool": tc["name"],
                                        "label": _tool_label(tc["name"]),
                                    },
                                )
                            )
                elif msg_type == "ToolMessage":
                    events.extend(self._tool_message_events(msg, thread_id))

        return events

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _tool_message_events(self, msg: Any, thread_id: str) -> list[StreamEvent]:
        events: list[StreamEvent] = []
        tool_name: str = getattr(msg, "name", "") or ""
        tool_call_id: str = getattr(msg, "tool_call_id", "") or ""

        # Decode content safely
        content: dict = {}
        raw = getattr(msg, "content", "")
        if isinstance(raw, str):
            try:
                import json
                content = json.loads(raw)
            except Exception:
                content = {}
        elif isinstance(raw, dict):
            content = raw

        # Source evidence from search_documents
        if tool_name in _SEARCH_TOOLS and isinstance(content, dict):
            for item in content.get("evidence", [])[:5]:
                if isinstance(item, dict):
                    events.append(
                        make_event(
                            thread_id,
                            "source.retrieved",
                            {
                                "source": item.get("source_name", ""),
                                "section": item.get("section", ""),
                                "page": item.get("page"),
                            },
                        )
                    )

        # Structured decision from evaluate_* tools
        if tool_name in _DECISION_TOOLS and isinstance(content, dict):
            events.append(
                make_event(
                    thread_id,
                    "decision.completed",
                    _safe_decision_data(tool_name, content),
                )
            )

        # tool.completed – safe subset only, no raw data
        status = "success" if content.get("success", True) else "error"
        events.append(
            make_event(
                thread_id,
                "tool.completed",
                {
                    "tool_call_id": tool_call_id,
                    "tool": tool_name,
                    "label": _tool_label(tool_name),
                    "status": status,
                },
            )
        )
        return events

    def _interrupt_events(self, interrupt_value: Any, thread_id: str) -> list[StreamEvent]:
        """Emit approval.required from a LangGraph __interrupt__ value."""
        # interrupt_value may be an Interrupt object or a plain dict depending on
        # the langgraph version.  Normalise to dict.
        data: dict = {}
        if hasattr(interrupt_value, "value"):
            raw = interrupt_value.value
        elif isinstance(interrupt_value, dict):
            raw = interrupt_value
        else:
            raw = {}

        if isinstance(raw, dict):
            data = raw
        elif hasattr(raw, "model_dump"):
            data = raw.model_dump(mode="json")

        return [make_event(thread_id, "approval.required", data)]


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

_TOOL_LABELS: dict[str, str] = {
    "search_documents": "Searching documentation",
    "get_order": "Looking up order",
    "get_ticket": "Looking up ticket",
    "get_my_account": "Fetching account details",
    "list_account_tickets": "Listing tickets",
    "evaluate_cancellation": "Calculating cancellation eligibility",
    "evaluate_service_credit": "Calculating service credit",
    "evaluate_ticket_sla": "Checking SLA status",
    "create_escalation": "Creating escalation",
}


def _tool_label(tool_name: str) -> str:
    return _TOOL_LABELS.get(tool_name, tool_name.replace("_", " ").capitalize())


def _safe_decision_data(tool_name: str, content: dict) -> dict:
    """Return the safe, UI-friendly subset of an evaluate_* tool result."""
    if tool_name == "evaluate_cancellation":
        return {
            "decision": "cancellation_allowed" if content.get("allowed") else "cancellation_not_allowed",
            "fee_inr": str(content["fee_inr"]) if content.get("fee_inr") is not None else None,
            "reason_code": content.get("reason_code"),
        }
    if tool_name == "evaluate_service_credit":
        return {
            "decision": "credit_eligible" if content.get("eligible") else "credit_not_eligible",
            "credit_inr": str(content["credit_inr"]) if content.get("credit_inr") is not None else None,
            "reason_code": content.get("reason_code"),
        }
    if tool_name == "evaluate_ticket_sla":
        return {
            "decision": "sla_breached" if content.get("breached") else "sla_not_breached",
            "severity": content.get("severity"),
            "breach_minutes": content.get("breach_minutes"),
            "requires_immediate_escalation": content.get("requires_immediate_escalation"),
        }
    return {}
