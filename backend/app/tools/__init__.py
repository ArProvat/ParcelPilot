"""Tool factories for agent-accessible capabilities."""
from app.tools.business_rules import create_business_rule_tools
from app.tools.document_search import create_document_search_tools
from app.tools.escalations import create_escalation_tools
from app.tools.structured_data import create_structured_data_tools


def create_agent_tools(session_factory=None):
    """Create all ParcelPilot tools.

    Tools do NOT close over a UserContext.  Each tool reads the caller's
    identity from ``config["configurable"]["user"]`` at invocation time,
    keeping agent construction independent of user identity.
    """
    return [
        *create_document_search_tools(session_factory=session_factory),
        *create_structured_data_tools(session_factory=session_factory),
        *create_business_rule_tools(session_factory=session_factory),
        *create_escalation_tools(session_factory=session_factory),
    ]


__all__ = [
    "create_agent_tools",
    "create_business_rule_tools",
    "create_document_search_tools",
    "create_escalation_tools",
    "create_structured_data_tools",
]
