"""End-to-end PDF → knowledge graph pipeline (asyncio).

    parse ─► chunk ─► embed chunks ─► write chunks
                                   └► extract (N chunks concurrently, bounded) ─► resolve ─► write graph

CPU-bound steps (PDF parsing, tokenising, embedding) run in worker threads;
LLM extraction runs as concurrent coroutines bounded by a semaphore. Every
stage transition is persisted to the (:Document) node and broadcast to live
subscribers, and a failure in one chunk's extraction degrades gracefully
instead of failing the whole document.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from pathlib import Path

from app.config import settings
from app.models import DocumentStatus, ExtractionResult, TextChunk
from app.models.schema import _now
from app.services.chunker import Chunker
from app.services.embeddings import Embedder, embed_async, get_embedder
from app.services.events import ProgressBroker
from app.services.events import broker as default_broker
from app.services.extractor import Extractor
from app.services.graph_store import GraphStore
from app.services.pdf_processor import PDFProcessor
from app.services.resolver import EntityResolver

logger = logging.getLogger(__name__)

# Fractions of the progress bar allotted to each stage.
_P_PARSED, _P_EMBEDDED, _P_EXTRACTED, _P_RESOLVED = 0.05, 0.15, 0.85, 0.92


class DocumentTooLarge(ValueError):
    pass


class Pipeline:
    def __init__(
        self,
        graph_store: GraphStore,
        extractor: Extractor | None = None,
        embedder: Embedder | None = None,
        broker: ProgressBroker | None = None,
        pdf: PDFProcessor | None = None,
        chunker: Chunker | None = None,
        on_complete: Callable[[], None] | None = None,
    ) -> None:
        self._gs = graph_store
        self._on_complete = on_complete
        self._extractor = extractor or Extractor()
        self._embedder = embedder
        self._broker = broker or default_broker
        self._pdf = pdf or PDFProcessor()
        self._chunker = chunker or Chunker(
            min_tokens=settings.chunk_min_tokens,
            max_tokens=settings.chunk_max_tokens,
            overlap_tokens=settings.chunk_overlap_tokens,
        )

    @property
    def embedder(self) -> Embedder:
        if self._embedder is None:
            self._embedder = get_embedder()
        return self._embedder

    async def _emit(self, doc: DocumentStatus, /, **changes) -> None:
        for k, v in changes.items():
            setattr(doc, k, v)
        doc.updated_at = _now()
        await self._gs.save_document(doc)
        self._broker.publish(doc.model_copy())

    async def process(self, pdf_path: str | Path, status: DocumentStatus) -> DocumentStatus:
        try:
            await self._emit(status, status="processing", stage="parsing", progress=0.01)
            pages = await asyncio.to_thread(self._pdf.extract, pdf_path)
            if len(pages) > settings.max_pages:
                raise DocumentTooLarge(
                    f"Document has {len(pages)} text pages; the limit is {settings.max_pages}."
                )
            if not pages:
                raise ValueError("No extractable text found (is this a scanned PDF?).")

            await self._emit(status, stage="chunking", page_count=len(pages), progress=_P_PARSED)
            chunks = await asyncio.to_thread(
                self._chunker.chunk_pages, pages, status.document_id, status.filename
            )

            await self._emit(status, stage="embedding", chunk_count=len(chunks))
            vecs = await embed_async([c.text for c in chunks], self.embedder)
            await self._gs.write_chunks(chunks, vecs)

            await self._emit(status, stage="extracting", progress=_P_EMBEDDED)
            results = await self._extract_all(chunks, status)

            await self._emit(status, stage="resolving", progress=_P_EXTRACTED)
            resolver = EntityResolver(embedder=self.embedder)

            def _resolve():
                rels = []
                for res in results:
                    rels.extend(resolver.resolve(res.entities, res.relationships))
                ents = resolver.all_entities
                return ents, [resolver.embedding_for(e) for e in ents], rels

            entities, ent_vecs, relationships = await asyncio.to_thread(_resolve)
            merged = await self._link_to_existing(entities, ent_vecs, relationships, status.document_id)

            await self._emit(
                status,
                stage="writing",
                progress=_P_RESOLVED,
                entity_count=len(entities),
                relationship_count=len(relationships),
            )
            await self._gs.write_graph(entities, ent_vecs, relationships)

            await self._emit(status, status="complete", stage="done", progress=1.0)
            logger.info(
                "Processed %s: %d chunks, %d entities (%d linked to other documents), %d relationships",
                status.filename,
                len(chunks),
                len(entities),
                merged,
                len(relationships),
            )
            if self._on_complete:
                self._on_complete()
        except Exception as exc:  # noqa: BLE001 - surface any failure to the user
            logger.exception("Pipeline failed for %s", status.filename)
            try:
                await self._emit(status, status="error", error=str(exc) or exc.__class__.__name__)
            except Exception:  # noqa: BLE001 - DB unreachable; the restart sweep will fail the job
                logger.exception("Could not record failure for %s", status.document_id)
        return status

    async def _link_to_existing(self, entities, vecs, relationships, document_id: str) -> int:
        """Cross-document entity resolution.

        Each new canonical entity is compared (vector index, same type) against
        entities already extracted from *other* documents; a match adopts the
        existing node's id, so the write merges provenance into it instead of
        creating a duplicate. Returns the number of entities linked.
        """
        rows = [
            {"idx": i, "type": e.type, "embedding": v.tolist()}
            for i, (e, v) in enumerate(zip(entities, vecs, strict=True))
            if v is not None
        ]
        matches = await self._gs.match_existing_entities(
            rows, settings.entity_similarity_threshold, exclude_document=document_id
        )
        remap: dict[str, str] = {}
        for idx, existing_id in matches.items():
            remap[entities[idx].id] = existing_id
            entities[idx].id = existing_id
        if remap:
            for r in relationships:
                r.source_entity_id = remap.get(r.source_entity_id, r.source_entity_id)
                r.target_entity_id = remap.get(r.target_entity_id, r.target_entity_id)
        return len(remap)

    async def _extract_all(self, chunks: list[TextChunk], status: DocumentStatus) -> list[ExtractionResult]:
        sem = asyncio.Semaphore(settings.extraction_concurrency)
        done = 0
        failures = 0
        lock = asyncio.Lock()

        async def one(chunk: TextChunk) -> ExtractionResult:
            nonlocal done, failures
            async with sem:
                try:
                    res = await self._extractor.extract_from_chunk(chunk)
                except Exception:  # noqa: BLE001 - one bad chunk must not sink the document
                    logger.exception("Extraction failed for chunk %s", chunk.id)
                    res = ExtractionResult(entities=[], relationships=[])
                    failures += 1
            async with lock:
                done += 1
                frac = done / max(len(chunks), 1)
                await self._emit(
                    status,
                    chunks_processed=done,
                    progress=_P_EMBEDDED + frac * (_P_EXTRACTED - _P_EMBEDDED),
                )
            return res

        # gather preserves input order, which keeps resolution deterministic.
        results = await asyncio.gather(*(one(c) for c in chunks))
        if chunks and failures == len(chunks):
            raise RuntimeError("Entity extraction failed for every chunk (check ANTHROPIC_API_KEY).")
        return results
