"""Entity resolution — deduplicate similar entities using embeddings + string similarity."""

import logging
from typing import Optional

import numpy as np
from sentence_transformers import SentenceTransformer

from app.config import settings
from app.models import Entity, Relationship

logger = logging.getLogger(__name__)


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    return float(np.dot(a, b) / denom) if denom > 0 else 0.0


class EntityResolver:
    """
    Merges near-duplicate entities discovered across chunks.

    Approach:
    1. Embed each entity's "name — type" string.
    2. For each new entity, find the most similar existing canonical entity.
    3. If similarity >= threshold (and types match), merge into the canonical.
    4. Update relationship pointers to use canonical IDs.
    """

    def __init__(self) -> None:
        self._model = SentenceTransformer(settings.embedding_model)
        self._threshold = settings.entity_similarity_threshold
        self._canonicals: list[Entity] = []
        self._canonical_embeddings: list[np.ndarray] = []
        # old_id -> canonical entity
        self._id_map: dict[str, Entity] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve(
        self,
        entities: list[Entity],
        relationships: list[Relationship],
    ) -> tuple[list[Entity], list[Relationship]]:
        """
        Resolve a batch of entities against the running canonical set.
        Returns deduplicated entities and patched relationships.
        """
        for entity in entities:
            canonical = self._find_or_create_canonical(entity)
            self._id_map[entity.id] = canonical

        # Patch relationship IDs
        resolved_rels: list[Relationship] = []
        seen_rels: set[tuple[str, str, str]] = set()

        for rel in relationships:
            src = self._id_map.get(rel.source_entity_id)
            tgt = self._id_map.get(rel.target_entity_id)
            if not src or not tgt or src.id == tgt.id:
                continue
            key = (src.id, tgt.id, rel.type)
            if key in seen_rels:
                continue
            seen_rels.add(key)
            resolved_rels.append(
                rel.model_copy(update={"source_entity_id": src.id, "target_entity_id": tgt.id})
            )

        return self._canonicals, resolved_rels

    def get_canonical(self, entity_id: str) -> Optional[Entity]:
        return self._id_map.get(entity_id)

    @property
    def all_entities(self) -> list[Entity]:
        return list(self._canonicals)

    # ------------------------------------------------------------------

    def _embed(self, entity: Entity) -> np.ndarray:
        text = f"{entity.name} ({entity.type})"
        return self._model.encode(text, normalize_embeddings=True)

    def _find_or_create_canonical(self, entity: Entity) -> Entity:
        if not self._canonicals:
            return self._add_canonical(entity)

        emb = self._embed(entity)
        best_sim = -1.0
        best_idx = -1

        for idx, (canon, canon_emb) in enumerate(
            zip(self._canonicals, self._canonical_embeddings)
        ):
            # Only consider same entity type
            if canon.type != entity.type:
                continue
            sim = _cosine(emb, canon_emb)
            if sim > best_sim:
                best_sim = sim
                best_idx = idx

        if best_sim >= self._threshold and best_idx >= 0:
            canonical = self._canonicals[best_idx]
            # Merge: add aliases and chunk references
            if entity.name not in canonical.aliases and entity.name != canonical.name:
                canonical.aliases.append(entity.name)
            for cid in entity.source_chunk_ids:
                if cid not in canonical.source_chunk_ids:
                    canonical.source_chunk_ids.append(cid)
            return canonical

        return self._add_canonical(entity)

    def _add_canonical(self, entity: Entity) -> Entity:
        self._canonicals.append(entity)
        self._canonical_embeddings.append(self._embed(entity))
        self._id_map[entity.id] = entity
        return entity
