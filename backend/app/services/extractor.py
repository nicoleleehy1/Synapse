"""LLM-based entity and relationship extraction using Claude structured outputs.

The response is constrained to a JSON schema generated from Pydantic models,
so there is no prompt-and-pray JSON parsing: Claude's output is validated
against `_ExtractionPayload` by the SDK before we ever see it.
"""

from __future__ import annotations

import logging
import re
from typing import Literal

import anthropic
from pydantic import BaseModel, Field

from app.config import settings
from app.models import Entity, ExtractionResult, Relationship, TextChunk

logger = logging.getLogger(__name__)

EntityType = Literal[
    "PERSON", "ORGANIZATION", "LOCATION", "CONCEPT", "EVENT", "TECHNOLOGY", "PRODUCT", "OTHER"
]


class _ExtractedEntity(BaseModel):
    name: str = Field(description="Canonical name: full names over pronouns or abbreviations.")
    type: EntityType
    description: str = Field(description="One sentence describing the entity, grounded in the text.")


class _ExtractedRelationship(BaseModel):
    source: str = Field(description="Exact `name` of an entity in the entities list.")
    target: str = Field(description="Exact `name` of an entity in the entities list.")
    type: str = Field(description="UPPERCASE_SNAKE_CASE verb, e.g. FOUNDED, PART_OF, CAUSES.")
    description: str = Field(description="One sentence explaining the relationship.")
    confidence: float = Field(description="0.0-1.0: how strongly the text supports this relationship.")


class _ExtractionPayload(BaseModel):
    entities: list[_ExtractedEntity]
    relationships: list[_ExtractedRelationship]


SYSTEM_PROMPT = """You build knowledge graphs from document excerpts.

From the excerpt, extract the entities worth representing as graph nodes and the
directional relationships between them.

- Extract only entities that are explicitly mentioned or strongly implied by the excerpt.
- Use one consistent, canonical name per entity (full names over pronouns or abbreviations).
- Relationship types are informative verbs in UPPERCASE_SNAKE_CASE (FOUNDED, ACQUIRED,
  WORKS_AT, LOCATED_IN, PART_OF, CAUSES, USES, AUTHORED, DEFINES, PRECEDES, ...).
  Avoid vague types like RELATED_TO when a precise verb fits.
- Every relationship's source and target must exactly match an entity name you listed.
- Confidence reflects how strongly the excerpt supports the relationship, not your
  general knowledge.
- If the excerpt has nothing notable, return empty lists."""

_REL_TYPE_RE = re.compile(r"[^A-Z0-9_]+")


class Extractor:
    def __init__(self, client: anthropic.AsyncAnthropic | None = None) -> None:
        self._client = client or anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key or None)

    async def extract_from_chunk(self, chunk: TextChunk) -> ExtractionResult:
        payload = await self._call_llm(chunk.text)
        if payload is None:
            return ExtractionResult(entities=[], relationships=[])
        return self.to_graph(payload, chunk)

    async def _call_llm(self, text: str) -> _ExtractionPayload | None:
        kwargs: dict = dict(
            model=settings.llm_model,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": f"<excerpt>\n{text}\n</excerpt>"}],
            output_format=_ExtractionPayload,
            output_config={"effort": settings.extraction_effort},
        )
        if settings.llm_fallbacks:
            response = await self._client.beta.messages.parse(
                betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs
            )
        else:
            response = await self._client.messages.parse(**kwargs)

        if response.stop_reason == "refusal":
            logger.warning("Extraction refused for a chunk; skipping it")
            return None
        if response.stop_reason == "max_tokens":
            logger.warning("Extraction hit max_tokens; skipping chunk")
            return None
        return response.parsed_output

    @staticmethod
    def to_graph(payload: _ExtractionPayload, chunk: TextChunk) -> ExtractionResult:
        """Convert the validated LLM payload into graph models tied to `chunk`."""
        entity_map: dict[str, Entity] = {}
        for e in payload.entities:
            name = e.name.strip()
            if not name or name.lower() in entity_map:
                continue
            entity_map[name.lower()] = Entity(
                name=name,
                type=e.type,
                description=e.description.strip() or None,
                source_document=chunk.document_name,
                document_id=chunk.document_id,
                source_chunk_ids=[chunk.id],
            )

        relationships: list[Relationship] = []
        for r in payload.relationships:
            src = entity_map.get(r.source.strip().lower())
            tgt = entity_map.get(r.target.strip().lower())
            if not src or not tgt or src.id == tgt.id:
                continue
            rel_type = _REL_TYPE_RE.sub("_", r.type.strip().upper().replace(" ", "_")).strip("_")
            relationships.append(
                Relationship(
                    source_entity_id=src.id,
                    target_entity_id=tgt.id,
                    type=rel_type or "RELATED_TO",
                    description=r.description.strip() or None,
                    confidence=max(0.0, min(1.0, r.confidence)),
                    source_chunk_id=chunk.id,
                    source_document=chunk.document_name,
                )
            )
        return ExtractionResult(entities=list(entity_map.values()), relationships=relationships)
