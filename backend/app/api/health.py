"""Health and readiness endpoints."""
from fastapi import APIRouter, Request
from sqlalchemy import func, select, text

from app.agent import llm_config_status
from app.config import settings
from app.models import Account, DatasetConfig, DocumentChunk


router = APIRouter()


@router.get("")
async def health():
    return {"status": "ok"}


@router.get("/ready")
async def ready(request: Request = None):
    return await readiness_status(request)


@router.get("/llm-config")
async def llm_config():
    return llm_config_status()


async def readiness_status(request: Request | None = None) -> dict:
    status = {
        "status": "ready",
        "environment": settings.APP_ENV,
        "database": "unknown",
        "schema": "unknown",
        "dataset": "unknown",
        "vector_store": "unknown",
        "checkpointer": "unknown",
        "agent": "unknown",
    }
    try:
        from app.db.session import AsyncSessionLocal

        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
            status["database"] = "ok"

            # Check schema / migrations
            if session.get_bind().dialect.name == "postgresql":
                version_exists = await session.scalar(
                    text("SELECT 1 FROM information_schema.tables WHERE table_name = 'alembic_version'")
                )
                status["schema"] = "ok" if version_exists else "missing"
            else:
                status["schema"] = "ok"

            dataset_count = await session.scalar(select(func.count()).select_from(DatasetConfig))
            account_count = await session.scalar(select(func.count()).select_from(Account))
            chunk_count = await session.scalar(select(func.count()).select_from(DocumentChunk))
            status["dataset"] = "loaded" if (dataset_count and account_count) else "missing"
            status["vector_store"] = "ok" if chunk_count else "missing"

            if session.get_bind().dialect.name == "postgresql":
                extension = await session.scalar(
                    text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
                )
                status["vector_store"] = "ok" if extension and chunk_count else "missing"
    except Exception as exc:
        status["status"] = "not_ready"
        status["database"] = "error"
        status["error"] = exc.__class__.__name__

    # Check checkpointer state and enforce production requirements
    if settings.APP_ENV == "production":
        status["checkpointer"] = "postgres_required"
        # In production, checkpointer must be Postgres-backed
        if not settings.DATABASE_URL or "postgresql" not in settings.DATABASE_URL:
            status["checkpointer"] = "error"
    else:
        status["checkpointer"] = "ok"

    # Check agent state if request context is provided
    if request and hasattr(request.app.state, "agent_stream_service") and request.app.state.agent_stream_service is not None:
        status["agent"] = "ready"
    else:
        status["agent"] = "ready"

    if any(status[key] in {"missing", "error", "not_ready"} for key in ("database", "schema", "dataset", "vector_store", "checkpointer")):
        status["status"] = "not_ready"

    return status

