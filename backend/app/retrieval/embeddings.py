"""Embedding providers for document chunks."""
from functools import lru_cache
from hashlib import blake2b
import re
from typing import Protocol

from app.config import settings
from app.db.types import EMBEDDING_DIMENSION


class EmbeddingProvider(Protocol):
    def embed(self, text: str) -> list[float]:
        ...


class HashEmbeddingProvider:
    """Deterministic local embedding substitute for development and tests."""

    def __init__(self, dimensions: int = EMBEDDING_DIMENSION) -> None:
        self.dimensions = dimensions

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        tokens = re.findall(r"[a-z0-9]+", text.lower())
        if not tokens:
            return vector

        for token in tokens:
            digest = blake2b(token.encode("utf-8"), digest_size=8).digest()
            bucket = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[bucket] += sign

        magnitude = sum(value * value for value in vector) ** 0.5
        if magnitude == 0:
            return vector
        return [value / magnitude for value in vector]


class SentenceTransformersEmbeddingProvider:
    """Local Hugging Face sentence-transformers embedding provider."""

    def __init__(
        self,
        model_name: str = "Qwen/Qwen3-Embedding-0.6B",
        dimensions: int = EMBEDDING_DIMENSION,
    ) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # pragma: no cover - depends on optional runtime package
            raise RuntimeError(
                "sentence-transformers is not installed. Install requirements or set "
                "EMBEDDING_PROVIDER=hash for tests/offline development."
            ) from exc

        self.model_name = model_name
        self.dimensions = dimensions
        self.model = SentenceTransformer(model_name)

    def embed(self, text: str) -> list[float]:
        vector = self.model.encode(
            text,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        values = [float(value) for value in vector.tolist()]
        if len(values) != self.dimensions:
            raise ValueError(
                f"Embedding model {self.model_name!r} returned {len(values)} dimensions; "
                f"database expects {self.dimensions}."
            )
        return values


@lru_cache(maxsize=1)
def get_embedding_provider() -> EmbeddingProvider:
    if settings.EMBEDDING_PROVIDER == "hash":
        return HashEmbeddingProvider()
    return SentenceTransformersEmbeddingProvider(settings.EMBEDDING_MODEL_NAME)
