"""Chat model factory for configured LLM providers."""

from app.config import settings


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

        kwargs = {
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


def llm_config_status() -> dict[str, object]:
    """Return non-secret LLM configuration state for diagnostics."""
    return {
        "provider": settings.LLM_PROVIDER,
        "model": settings.LLM_MODEL,
        "base_url": _base_url_for_provider(),
        "api_key_configured": _api_key_configured(),
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
