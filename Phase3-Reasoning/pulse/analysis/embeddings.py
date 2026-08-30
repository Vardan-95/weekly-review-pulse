"""Embedding batching — Architecture.md §3 (`analysis/embeddings.py`).

The real embedding model is lazily imported and never exercised by unit
tests (same pattern as Phase 2's ingestion clients) — tests inject a fake
deterministic EmbeddingClient instead.
"""
from __future__ import annotations

from typing import Protocol


class EmbeddingClient(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class SentenceTransformerEmbeddingClient:
    """Real client, backed by `sentence-transformers`. Not exercised by
    unit tests."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self._model_name = model_name
        self._model = None

    def embed(self, texts: list[str]) -> list[list[float]]:
        if self._model is None:
            from sentence_transformers import SentenceTransformer  # lazy import

            self._model = SentenceTransformer(self._model_name)
        return self._model.encode(texts).tolist()


DEFAULT_BATCH_SIZE = 64


def embed_texts(
    texts: list[str],
    *,
    client: EmbeddingClient,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> list[list[float]]:
    """Batch `texts` through `client.embed()` in chunks of `batch_size`,
    preserving order."""
    if not texts:
        return []
    vectors: list[list[float]] = []
    for start in range(0, len(texts), batch_size):
        chunk = texts[start : start + batch_size]
        vectors.extend(client.embed(chunk))
    return vectors
