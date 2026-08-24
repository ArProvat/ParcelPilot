"""LangGraph PostgreSQL checkpointer factory.

Uses ``langgraph-checkpoint-postgres`` for persistent checkpointing.
The checkpointer is created once during FastAPI lifespan and shared across
all agent invocations.

Environment behavior:
- TEST: Uses MemorySaver (fast, isolated, in-memory) unless configured otherwise.
- DEVELOPMENT: Prefers AsyncPostgresSaver; falls back to MemorySaver with an
  explicit WARNING log if PostgreSQL is unreachable.
- PRODUCTION: AsyncPostgresSaver is mandatory. Fails closed (raises RuntimeError)
  if persistent checkpointing cannot initialize. Silent MemorySaver fallback is
  strictly forbidden.
"""
from __future__ import annotations

import logging
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)


async def create_checkpointer(app_env: str | None = None) -> Any:
    """Create and set up the checkpointer according to environment policy.

    Parameters
    ----------
    app_env:
        Environment override ("test", "development", "production").
        Defaults to ``settings.APP_ENV``.

    Returns
    -------
    A ready-to-use checkpointer instance (AsyncPostgresSaver or MemorySaver).
    """
    env = (app_env or settings.APP_ENV or "development").lower()

    if env == "test":
        from langgraph.checkpoint.memory import MemorySaver

        logger.info("langgraph_checkpointer_test_mode_memory_saver")
        return MemorySaver()

    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        from psycopg_pool import AsyncConnectionPool

        # DATABASE_URL uses the asyncpg dialect prefix; psycopg3 needs plain postgresql://.
        dsn = (
            settings.DATABASE_URL
            .replace("postgresql+asyncpg://", "postgresql://")
            .replace("postgresql+psycopg://", "postgresql://")
        )

        pool = AsyncConnectionPool(conninfo=dsn, max_size=20, open=False)
        await pool.open()
        saver = AsyncPostgresSaver(pool)
        await saver.setup()
        logger.info("langgraph_checkpointer_ready", extra={"env": env})
        return saver

    except Exception as exc:
        if env == "production":
            logger.critical(
                "langgraph_production_checkpointer_init_failed_fail_closed",
                extra={"error": str(exc), "env": env},
                exc_info=True,
            )
            raise RuntimeError(
                "PostgreSQL checkpointer initialization failed in production. "
                "Persistent checkpointing is mandatory for human-in-the-loop state durability."
            ) from exc

        if env == "development":
            logger.warning(
                "langgraph_development_postgres_unavailable_fallback_memory: "
                "PostgreSQL checkpointer unavailable in development mode. "
                "Falling back to MemorySaver (in-memory checkpointing). State will not persist across restarts.",
                exc_info=True,
            )
            from langgraph.checkpoint.memory import MemorySaver

            return MemorySaver()

        logger.exception("langgraph_checkpointer_init_failed")
        raise


async def close_checkpointer(checkpointer: Any) -> None:
    """Cleanly close the checkpointer connection pool on shutdown."""
    if checkpointer is None:
        return
    try:
        conn = getattr(checkpointer, "conn", None)
        if conn is not None and hasattr(conn, "close"):
            await conn.close()
    except Exception:
        logger.warning("langgraph_checkpointer_close_failed", exc_info=True)

