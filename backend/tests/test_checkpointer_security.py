"""Tests for checkpointer fail-closed security and environment policies."""
import logging
from unittest.mock import AsyncMock, patch

import pytest
from langgraph.checkpoint.memory import MemorySaver

from app.agent.checkpointer import close_checkpointer, create_checkpointer


@pytest.mark.asyncio
async def test_production_checkpointer_fails_closed_when_postgres_unavailable():
    """In production, checkpointer failure must raise RuntimeError and never fall back silently to MemorySaver."""
    import psycopg_pool

    with patch.object(psycopg_pool.AsyncConnectionPool, "open", side_effect=ConnectionRefusedError("PostgreSQL unreachable")):
        with pytest.raises(RuntimeError) as exc_info:
            await create_checkpointer(app_env="production")

        assert "mandatory" in str(exc_info.value).lower()
        assert "production" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_development_checkpointer_falls_back_to_memory_with_warning(caplog):
    """In development, checkpointer failure falls back to MemorySaver with an explicit WARNING log."""
    import psycopg_pool

    with patch.object(psycopg_pool.AsyncConnectionPool, "open", side_effect=ConnectionRefusedError("Dev DB down")):
        with caplog.at_level(logging.WARNING):
            checkpointer = await create_checkpointer(app_env="development")

        assert isinstance(checkpointer, MemorySaver)
        assert any("fallback_memory" in record.message or "Falling back to MemorySaver" in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_test_environment_uses_memory_saver():
    """In test environment, create_checkpointer returns MemorySaver directly without attempting DB network connection."""
    checkpointer = await create_checkpointer(app_env="test")
    assert isinstance(checkpointer, MemorySaver)


@pytest.mark.asyncio
async def test_close_checkpointer_handles_all_types_safely():
    """close_checkpointer must not crash for MemorySaver, None, or standard connection objects."""
    # None
    await close_checkpointer(None)

    # MemorySaver
    mem_saver = MemorySaver()
    await close_checkpointer(mem_saver)

    # Mock with conn.close
    mock_saver = AsyncMock()
    mock_saver.conn = AsyncMock()
    mock_saver.conn.close = AsyncMock()
    await close_checkpointer(mock_saver)
    mock_saver.conn.close.assert_awaited_once()
