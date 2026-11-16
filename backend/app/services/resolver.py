"""Entity resolution: merge near-duplicate entities discovered across chunks.

1. Exact match on (normalised name, type) short-circuits the embedding step.
2. Otherwise embed "name (type)" and compare against all canonicals of the same
   type in one matrix multiply (embeddings are L2-normalised, so dot = cosine).
3. If the best similarity >= threshold, merge (aliases + chunk provenance);
   otherwise the entity becomes a new canonical.
4. Relationship endpoints are rewritten to canonical ids and de-duplicated.

Embeddings for a whole batch are computed in a single call, so resolving N
entities costs one model invocation per chunk rather than N.
"""

from __future__ import annotations

import logging
import re

import numpy as np

from app.config import settings
from app.models import Entity, Relationship
from app.services.embeddings import Embedder, get_embedder

logger = logging.getLogger(__name__)

_WS = re.compile(r"\s+")


def _norm(name: str) -> str:
    return _WS.sub(" ", name.strip().lower())


class EntityResolver:
    def __init__(self, embedder: Embedder | None = None, threshold: float | None = None) -> None:
        self._embedder = embedder or get_embedder()
        self._threshold = settings.entity_similarity_threshold if threshold is None else threshold
        self._canonicals: list[Entity] = []
        self._by_key: dict[tuple[str, str], Entity] = {}
        # Per-type embedding matrices, row i ↔ self._type_members[type][i]
        self._type_vecs: dict[str, np.ndarray] = {}
        self._type_members: dict[str, list[Entity]] = {}
        self._id_map: dict[str, Entity] = {}
        self._seen_rels: set[tuple[str, str, str]] = set()

    # ------------------------------------------------------------------

    def resolve(self, entities: list[Entity], relationships: list[Relationship]) -> list[Relationship]:
        """Fold a batch into the canonical set and return its de-duplicated relationships."""
        pending: list[Entity] = []
        for e in entities:
            hit = self._by_key.get((_norm(e.name), e.type))
            if hit:
                self._merge(hit, e)
            else:
                pending.append(e)

        if pending:
            vecs = self._embedder.embed([f"{e.name} ({e.type})" for e in pending])
            for e, v in zip(pending, vecs, strict=True):
                # Re-check exact key: an earlier entity in this same batch may have created it
                hit = self._by_key.get((_norm(e.name), e.type)) or self._nearest(e.type, v)
                if hit:
                    self._merge(hit, e)
                else:
                    self._add(e, v)

        out: list[Relationship] = []
        for rel in relationships:
            src = self._id_map.get(rel.source_entity_id)
            tgt = self._id_map.get(rel.target_entity_id)
            if not src or not tgt or src.id == tgt.id:
                continue
            key = (src.id, tgt.id, rel.type)
            if key in self._seen_rels:
                continue
            self._seen_rels.add(key)
            out.append(rel.model_copy(update={"source_entity_id": src.id, "target_entity_id": tgt.id}))
        return out

    @property
    def all_entities(self) -> list[Entity]:
        return list(self._canonicals)

    def embedding_for(self, entity: Entity) -> np.ndarray | None:
        members = self._type_members.get(entity.type, [])
        for i, m in enumerate(members):
            if m.id == entity.id:
                return self._type_vecs[entity.type][i]
        return None

    # ------------------------------------------------------------------

    def _nearest(self, type_: str, vec: np.ndarray) -> Entity | None:
        mat = self._type_vecs.get(type_)
        if mat is None or len(mat) == 0:
            return None
        sims = mat @ vec
        idx = int(np.argmax(sims))
        return self._type_members[type_][idx] if sims[idx] >= self._threshold else None

    def _merge(self, canonical: Entity, dup: Entity) -> None:
        self._id_map[dup.id] = canonical
        if dup.name != canonical.name and dup.name not in canonical.aliases:
            canonical.aliases.append(dup.name)
        for cid in dup.source_chunk_ids:
            if cid not in canonical.source_chunk_ids:
                canonical.source_chunk_ids.append(cid)
        if not canonical.description and dup.description:
            canonical.description = dup.description

    def _add(self, entity: Entity, vec: np.ndarray) -> None:
        self._canonicals.append(entity)
        self._by_key[(_norm(entity.name), entity.type)] = entity
        self._id_map[entity.id] = entity
        mat = self._type_vecs.get(entity.type)
        self._type_vecs[entity.type] = vec[None, :] if mat is None else np.vstack([mat, vec])
        self._type_members.setdefault(entity.type, []).append(entity)
