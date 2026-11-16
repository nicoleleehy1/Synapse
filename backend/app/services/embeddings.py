"""Text embeddings.

Uses fastembed (ONNX Runtime) instead of sentence-transformers + PyTorch: the
same all-MiniLM-L6-v2 weights, ~10x smaller container image, and fast CPU
inference. The model is loaded once per process and shared.

`Embedder` is a protocol so tests (and alternative providers) can swap in a
different implementation without touching callers.
"""

from __future__ import annotations

import asyncio
import hashlib
import threading
from typing import Protocol

import numpy as np

from app.config import settings


class Embedder(Protocol):
    dim: int

    def embed(self, texts: list[str]) -> np.ndarray:
        """Return an (n, dim) float32 array of L2-normalised embeddings."""
        ...


class FastEmbedEmbedder:
    def __init__(self, model_name: str | None = None, cache_dir: str | None = None) -> None:
        from fastembed import TextEmbedding  # imported lazily: heavy import

        self._model = TextEmbedding(
            model_name or settings.embedding_model,
            cache_dir=cache_dir or settings.embedding_cache_dir,
        )
        self.dim = settings.embedding_dim
        self._lock = threading.Lock()

    def embed(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        with self._lock:  # ONNX session is not guaranteed re-entrant
            vecs = np.asarray(list(self._model.embed(texts)), dtype=np.float32)
        return _normalise(vecs)


class HashEmbedder:
    """Deterministic, dependency-free embedder for tests and offline development.

    Bag-of-character-trigrams hashed into `dim` buckets: strings that share
    most of their trigrams land close together, which is enough to exercise
    similarity-based code paths.
    """

    def __init__(self, dim: int = 384) -> None:
        self.dim = dim

    def embed(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, text in enumerate(texts):
            t = f"  {text.lower()}  "
            for j in range(len(t) - 2):
                h = int.from_bytes(hashlib.blake2b(t[j : j + 3].encode(), digest_size=4).digest(), "little")
                out[i, h % self.dim] += 1.0
        return _normalise(out)


def _normalise(vecs: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (vecs / norms).astype(np.float32)


_embedder: Embedder | None = None
_embedder_lock = threading.Lock()


def get_embedder() -> Embedder:
    global _embedder
    if _embedder is None:
        with _embedder_lock:
            if _embedder is None:
                _embedder = (
                    HashEmbedder(settings.embedding_dim)
                    if settings.embedding_provider == "hash"
                    else FastEmbedEmbedder()
                )
    return _embedder


def set_embedder(embedder: Embedder | None) -> None:
    """Override the process-wide embedder (used by tests)."""
    global _embedder
    _embedder = embedder


async def embed_async(texts: list[str], embedder: Embedder | None = None) -> np.ndarray:
    """Run embedding in a worker thread so the event loop stays responsive."""
    emb = embedder or get_embedder()
    return await asyncio.to_thread(emb.embed, texts)
