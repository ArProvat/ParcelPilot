"""Tool factories for agent-accessible capabilities."""
from app.tools.business_rules import create_business_rule_tools
from app.tools.document_search import create_document_search_tools
from app.tools.structured_data import create_structured_data_tools


def create_agent_tools(user, session_factory=None):
    return [
        *create_document_search_tools(user, session_factory=session_factory),
        *create_structured_data_tools(user, session_factory=session_factory),
        *create_business_rule_tools(user, session_factory=session_factory),
    ]


__all__ = [
    "create_agent_tools",
    "create_business_rule_tools",
    "create_document_search_tools",
    "create_structured_data_tools",
]
