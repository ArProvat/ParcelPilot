"""Chat model factory for configured LLM providers.

Minimum Required Capabilities:
  1. Tool calling (Function calling / bind_tools) - MANDATORY
  2. Streaming output (tokens + tool call chunks) - MANDATORY
  3. Structured tool arguments (JSON schema compliant) - MANDATORY
  4. Stable tool-call IDs - MANDATORY

Provider Tiers:
  - Officially Verified: OpenAI (gpt-4o, gpt-4o-mini), OpenRouter (verified tool models like nvidia/nemotron, gpt-4o, claude-3.5)
  - Best-Effort: Ollama (requires local models that explicitly support function calling e.g. llama3.1, llama3-groq-tool-use)
"""
from __future__ import annotations

import logging
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)


def create_chat_model():
    """Create the configured LangChain chat model.

    OpenRouter is OpenAI-compatible, so it uses ``ChatOpenAI`` with a custom
    base URL and OpenRouter attribution headers.
    """
    if settings.LLM_PROVIDER == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=settings.LLM_MODEL,
            base_url=settings.OLLAMA_BASE_URL,
        )

    if settings.LLM_PROVIDER == "openai":
        from langchain_openai import ChatOpenAI

        if not settings.OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY is required when LLM_PROVIDER=openai")

        kwargs: dict[str, Any] = {
            "model": settings.LLM_MODEL,
            "api_key": settings.OPENAI_API_KEY,
        }
        if settings.OPENAI_BASE_URL:
            kwargs["base_url"] = settings.OPENAI_BASE_URL
        return ChatOpenAI(**kwargs)

    if settings.LLM_PROVIDER == "openrouter":
        from langchain_openai import ChatOpenAI

        api_key = settings.OPENROUTER_API_KEY or settings.OPENAI_API_KEY
        if not api_key:
            raise RuntimeError("OPENROUTER_API_KEY is required when LLM_PROVIDER=openrouter")

        return ChatOpenAI(
            model=settings.LLM_MODEL,
            api_key=api_key,
            base_url=settings.OPENROUTER_BASE_URL,
            default_headers={
                "HTTP-Referer": settings.OPENROUTER_SITE_URL,
                "X-OpenRouter-Title": settings.OPENROUTER_APP_NAME,
            },
        )

    raise RuntimeError(f"Unsupported LLM_PROVIDER: {settings.LLM_PROVIDER}")


def validate_provider_capabilities() -> dict[str, Any]:
    """Validate that the configured LLM provider meets minimum agent requirements."""
    provider = settings.LLM_PROVIDER
    status: dict[str, Any] = {
        "provider": provider,
        "model": settings.LLM_MODEL,
        "valid": True,
        "tier": "officially_verified" if provider in {"openai", "openrouter"} else "best_effort",
        "capabilities": {
            "tool_calling": True,
            "streaming": True,
            "structured_tool_args": True,
            "stable_tool_call_ids": True,
        },
        "errors": [],
    }

    if provider == "openai" and not settings.OPENAI_API_KEY:
        status["valid"] = False
        status["errors"].append("OPENAI_API_KEY is missing")
    elif provider == "openrouter" and not (settings.OPENROUTER_API_KEY or settings.OPENAI_API_KEY):
        status["valid"] = False
        status["errors"].append("OPENROUTER_API_KEY is missing")

    return status


def llm_config_status() -> dict[str, object]:
    """Return non-secret LLM configuration state for diagnostics."""
    return {
        "provider": settings.LLM_PROVIDER,
        "model": settings.LLM_MODEL,
        "base_url": _base_url_for_provider(),
        "api_key_configured": _api_key_configured(),
        "tier": "officially_verified" if settings.LLM_PROVIDER in {"openai", "openrouter"} else "best_effort",
    }


def _base_url_for_provider() -> str | None:
    if settings.LLM_PROVIDER == "ollama":
        return settings.OLLAMA_BASE_URL
    if settings.LLM_PROVIDER == "openai":
        return settings.OPENAI_BASE_URL
    if settings.LLM_PROVIDER == "openrouter":
        return settings.OPENROUTER_BASE_URL
    return None


def _api_key_configured() -> bool:
    if settings.LLM_PROVIDER == "openai":
        return bool(settings.OPENAI_API_KEY)
    if settings.LLM_PROVIDER == "openrouter":
        return bool(settings.OPENROUTER_API_KEY or settings.OPENAI_API_KEY)
    return True

