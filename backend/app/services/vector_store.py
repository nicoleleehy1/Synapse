"""FAISS-backed vector store for text chunk embeddings."""

import json
import logging
import os
from pathlib import Path

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

from app.config import settings
from app.models import TextChunk

logger = logging.getLogger(__name__)

_DIM = 384  # all-MiniLM-L6-v2 output dimension


class VectorStore:
    def __init__(self) -> None:
        self._model = SentenceTransformer(settings.embedding_model)
        self._index: faiss.Index = faiss.IndexFlatIP(_DIM)  # inner product on L2-normalised = cosine
        # metadata: list of {"chunk_id", "document_id", "document_name", "page_number", "text"}
        self._metadata: list[dict] = []
        self._load_if_exists()

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def add_chunks(self, chunks: list[TextChunk]) -> list[np.ndarray]:
        """Embed and index chunks. Returns per-chunk embedding vectors."""
        texts = [c.text for c in chunks]
        embeddings = self._embed(texts)

        self._index.add(embeddings)
        for chunk, emb in zip(chunks, embeddings):
            self._metadata.append({
                "chunk_id": chunk.id,
                "document_id": chunk.document_id,
                "document_name": chunk.document_name,
                "page_number": chunk.page_number,
                "text": chunk.text,
            })

        self._save()
        return [embeddings[i] for i in range(len(chunks))]

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def search(self, query: str, top_k: int = 5, document_id: str | None = None) -> list[dict]:
        """
        Return top_k most similar chunks.
        Each result: {"chunk_id", "document_id", "document_name",
                      "page_number", "text", "similarity_score"}
        """
        if self._index.ntotal == 0:
            return []

        q_emb = self._embed([query])
        scores, indices = self._index.search(q_emb, min(top_k * 3, self._index.ntotal))

        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0:
                continue
            meta = self._metadata[idx]
            if document_id and meta["document_id"] != document_id:
                continue
            results.append({**meta, "similarity_score": float(score)})
            if len(results) >= top_k:
                break

        return results

    def delete_document(self, document_id: str) -> None:
        """Remove all chunks belonging to a document (rebuild index)."""
        keep = [m for m in self._metadata if m["document_id"] != document_id]
        if len(keep) == len(self._metadata):
            return

        self._metadata = keep
        self._index = faiss.IndexFlatIP(_DIM)
        if keep:
            texts = [m["text"] for m in keep]
            embs = self._embed(texts)
            self._index.add(embs)
        self._save()

    # ------------------------------------------------------------------

    def _embed(self, texts: list[str]) -> np.ndarray:
        embs = self._model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return embs.astype(np.float32)

    def _save(self) -> None:
        faiss.write_index(self._index, settings.faiss_index_path)
        with open(settings.faiss_metadata_path, "w") as f:
            json.dump(self._metadata, f)

    def _load_if_exists(self) -> None:
        if Path(settings.faiss_index_path).exists() and Path(settings.faiss_metadata_path).exists():
            try:
                self._index = faiss.read_index(settings.faiss_index_path)
                with open(settings.faiss_metadata_path) as f:
                    self._metadata = json.load(f)
                logger.info("Loaded FAISS index (%d vectors)", self._index.ntotal)
            except Exception as e:
                logger.warning("Could not load FAISS index: %s", e)
