"""Health endpoints."""
from fastapi import APIRouter
from sqlalchemy import func, select, text

from app.db.session import AsyncSessionLocal
from app.models import Account, DatasetConfig, DocumentChunk


router = APIRouter()


@router.get("")
async def health():
    return {"status": "ok"}


@router.get("/ready")
async def ready():
    return await readiness_status()


async def readiness_status() -> dict:
    status = {
        "status": "ready",
        "database": "unknown",
        "dataset": "unknown",
        "vector_store": "unknown",
    }
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
            status["database"] = "ok"

            dataset_count = await session.scalar(select(func.count()).select_from(DatasetConfig))
            account_count = await session.scalar(select(func.count()).select_from(Account))
            chunk_count = await session.scalar(select(func.count()).select_from(DocumentChunk))
            status["dataset"] = "loaded" if dataset_count and account_count else "missing"
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

    if any(status[key] in {"missing", "error"} for key in ("database", "dataset", "vector_store")):
        status["status"] = "not_ready"

    return status
