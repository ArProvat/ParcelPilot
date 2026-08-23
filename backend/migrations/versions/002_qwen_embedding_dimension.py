"""switch document embeddings to qwen 1024 dimensions

Revision ID: 002_qwen_embedding_dimension
Revises: 001_initial_schema
Create Date: 2026-08-23 00:00:00
"""
from typing import Sequence, Union

from alembic import op


revision: str = "002_qwen_embedding_dimension"
down_revision: Union[str, None] = "001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Existing MiniLM vectors are 384-dimensional and cannot be cast into a
    # 1024-dimensional pgvector column. Clear them, resize the column, and let
    # the idempotent document bootstrap repopulate Qwen embeddings.
    op.execute("UPDATE document_chunks SET embedding = NULL")
    op.execute(
        "ALTER TABLE document_chunks "
        "ALTER COLUMN embedding TYPE vector(1024) "
        "USING NULL::vector(1024)"
    )


def downgrade() -> None:
    op.execute("UPDATE document_chunks SET embedding = NULL")
    op.execute(
        "ALTER TABLE document_chunks "
        "ALTER COLUMN embedding TYPE vector(384) "
        "USING NULL::vector(384)"
    )
