"""Database column types shared by SQLAlchemy models."""
from sqlalchemy import JSON

try:
    from pgvector.sqlalchemy import Vector
except ImportError:  # pragma: no cover - exercised only without optional pgvector installed
    Vector = None


EMBEDDING_DIMENSION = 1024


def embedding_column_type():
    """Use pgvector on PostgreSQL and JSON elsewhere for lightweight tests."""
    if Vector is None:
        return JSON
    return JSON().with_variant(Vector(EMBEDDING_DIMENSION), "postgresql")
