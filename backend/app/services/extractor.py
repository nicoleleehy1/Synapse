"""LLM-based entity and relationship extraction using Claude."""

import json
import logging
import re
from typing import Any

import anthropic

from app.config import settings
from app.models import Entity, ExtractionResult, Relationship, TextChunk

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a knowledge graph extraction engine. Given a text chunk, extract:
1. ENTITIES — named things worth representing as graph nodes.
2. RELATIONSHIPS — directional connections between entities.

Output ONLY valid JSON matching this exact schema (no markdown, no commentary):

{
  "entities": [
    {
      "name": "string — canonical name",
      "type": "PERSON | ORGANIZATION | LOCATION | CONCEPT | EVENT | TECHNOLOGY | PRODUCT | OTHER",
      "description": "string — one sentence description (optional)"
    }
  ],
  "relationships": [
    {
      "source": "entity name (must appear in entities list)",
      "target": "entity name (must appear in entities list)",
      "type": "UPPERCASE_SNAKE_CASE relationship verb",
      "description": "string — one sentence explanation (optional)",
      "confidence": 0.0–1.0
    }
  ]
}

Rules:
- Only extract entities that are explicitly mentioned or strongly implied.
- Use consistent, canonical names (full names over pronouns).
- Relationship types should be informative verbs: FOUNDED, ACQUIRED, WORKS_AT, LOCATED_IN,
  PART_OF, CAUSES, USES, AUTHORED, COLLABORATED_WITH, FUNDED_BY, etc.
- Confidence reflects how certain the relationship is given the text (not your general knowledge).
- If nothing notable is present, return {"entities": [], "relationships": []}.
"""


class Extractor:
    def __init__(self) -> None:
        self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    def extract_from_chunk(self, chunk: TextChunk, document_name: str) -> ExtractionResult:
        raw = self._call_llm(chunk.text)
        return self._parse(raw, chunk, document_name)

    # ------------------------------------------------------------------

    def _call_llm(self, text: str) -> str:
        message = self._client.messages.create(
            model=settings.llm_model,
            max_tokens=2048,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": f"Extract entities and relationships from:\n\n{text}"}],
        )
        return message.content[0].text

    def _parse(self, raw: str, chunk: TextChunk, document_name: str) -> ExtractionResult:
        # Strip markdown code fences if present
        raw = re.sub(r"```(?:json)?", "", raw).strip()
        try:
            data: dict[str, Any] = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Failed to parse LLM JSON output: %s", raw[:200])
            return ExtractionResult(entities=[], relationships=[])

        entity_map: dict[str, Entity] = {}

        for e_data in data.get("entities", []):
            name = (e_data.get("name") or "").strip()
            if not name:
                continue
            entity = Entity(
                name=name,
                type=e_data.get("type", "OTHER").upper(),
                description=e_data.get("description"),
                source_document=document_name,
                source_chunk_ids=[chunk.id],
            )
            entity_map[name.lower()] = entity

        relationships: list[Relationship] = []
        for r_data in data.get("relationships", []):
            src_name = (r_data.get("source") or "").strip().lower()
            tgt_name = (r_data.get("target") or "").strip().lower()
            if src_name not in entity_map or tgt_name not in entity_map:
                continue
            rel_type = re.sub(r"\s+", "_", (r_data.get("type") or "RELATED_TO").upper())
            confidence = float(r_data.get("confidence", 1.0))
            confidence = max(0.0, min(1.0, confidence))
            rel = Relationship(
                source_entity_id=entity_map[src_name].id,
                target_entity_id=entity_map[tgt_name].id,
                type=rel_type,
                description=r_data.get("description"),
                confidence=confidence,
                source_chunk_id=chunk.id,
                source_document=document_name,
            )
            relationships.append(rel)

        return ExtractionResult(
            entities=list(entity_map.values()),
            relationships=relationships,
        )
