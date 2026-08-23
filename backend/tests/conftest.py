"""Shared test configuration."""
import os


# Keep unit/integration tests deterministic and offline. Production/Docker uses
# sentence-transformers via environment configuration.
os.environ.setdefault("EMBEDDING_PROVIDER", "hash")
