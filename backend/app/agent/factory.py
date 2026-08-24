"""LangGraph agent assembly for ParcelPilot.

The factory is intentionally kept free of user identity.  UserContext is
injected at *invocation* time via ``config["configurable"]["user"]`` so the
same compiled agent graph is reused for every request.
"""
from langchain_core.messages import SystemMessage

from app.agent.prompt import SYSTEM_PROMPT


def create_parcelpilot_agent(model, tools, checkpointer):
    """Assemble the ParcelPilot ReAct agent.

    Parameters
    ----------
    model:
        A LangChain chat model (ChatOpenAI, ChatOllama, …).
    tools:
        Pre-built list of LangChain ``StructuredTool`` objects.  These must
        already have ``session_factory`` captured in their closures; they do
        NOT close over a ``UserContext`` – that is passed via config.
    checkpointer:
        An ``AsyncPostgresSaver`` (or compatible) for durable thread state.

    Returns
    -------
    A compiled LangGraph ``CompiledGraph`` ready for ``astream`` calls.
    """
    try:
        from langchain.agents import create_agent

        return create_agent(
            model=model,
            tools=tools,
            system_prompt=SYSTEM_PROMPT,
            checkpointer=checkpointer,
        )
    except (ImportError, TypeError):
        from langgraph.prebuilt import create_react_agent

        return create_react_agent(
            model=model,
            tools=tools,
            prompt=SystemMessage(content=SYSTEM_PROMPT),
            checkpointer=checkpointer,
        )
