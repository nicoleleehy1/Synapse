"""End-to-end PDF → Knowledge Graph pipeline."""

import logging
import uuid
from pathlib import Path

from app.models import DocumentStatus
from app.services.chunker import Chunker
from app.services.extractor import Extractor
from app.services.graph_store import GraphStore
from app.services.pdf_processor import PDFProcessor
from app.services.resolver import EntityResolver
from app.services.vector_store import VectorStore

logger = logging.getLogger(__name__)


class Pipeline:
    def __init__(
        self,
        graph_store: GraphStore,
        vector_store: VectorStore,
    ) -> None:
        self._pdf = PDFProcessor()
        self._chunker = Chunker()
        self._extractor = Extractor()
        self._gs = graph_store
        self._vs = vector_store

    def process(self, pdf_path: str | Path, document_id: str, filename: str) -> DocumentStatus:
        status = DocumentStatus(
            document_id=document_id,
            filename=filename,
            status="processing",
        )

        try:
            # 1. Extract text
            logger.info("Extracting text from %s", filename)
            pages = self._pdf.extract(pdf_path)
            status.page_count = len(pages)

            # 2. Chunk
            logger.info("Chunking %d pages", len(pages))
            chunks = self._chunker.chunk_pages(pages, document_id, filename)
            status.chunk_count = len(chunks)

            # 3. Store chunks in Neo4j + FAISS
            logger.info("Indexing %d chunks", len(chunks))
            self._vs.add_chunks(chunks)
            for chunk in chunks:
                self._gs.upsert_chunk_node(
                    chunk_id=chunk.id,
                    text=chunk.text,
                    page=chunk.page_number,
                    document_id=document_id,
                    document_name=filename,
                )

            # 4. Extract entities & relationships (per-chunk), then resolve
            resolver = EntityResolver()
            all_entities = []
            all_relationships = []

            for chunk in chunks:
                logger.debug("Extracting from chunk %s (page %d)", chunk.id, chunk.page_number)
                result = self._extractor.extract_from_chunk(chunk, filename)
                ents, rels = resolver.resolve(result.entities, result.relationships)
                all_relationships.extend(rels)

            all_entities = resolver.all_entities
            status.entity_count = len(all_entities)
            status.relationship_count = len(all_relationships)

            # 5. Persist graph
            logger.info(
                "Writing %d entities, %d relationships to Neo4j",
                len(all_entities),
                len(all_relationships),
            )
            for entity in all_entities:
                self._gs.upsert_entity(entity)
                for cid in entity.source_chunk_ids:
                    self._gs.link_entity_to_chunk(entity.id, cid)

            for rel in all_relationships:
                self._gs.upsert_relationship(rel)

            status.status = "complete"
            logger.info("Pipeline complete for %s", filename)

        except Exception as exc:
            logger.exception("Pipeline failed for %s: %s", filename, exc)
            status.status = "error"
            status.error = str(exc)

        return status
