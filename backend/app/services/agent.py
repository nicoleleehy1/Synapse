"""GraphRAG question-answering agent.

Instead of a fixed retrieve-then-generate pipeline, Claude plans its own
retrieval over five tools and streams its answer:

  search_passages   vector search over source passages (citable evidence)
  search_entities   hybrid full-text + vector lookup of graph nodes
  explore_entities  multi-hop neighbourhood expansion around entities
  search_topics     community reports, for "big picture" / corpus-level questions
  run_cypher        read-only Cypher for counting, ranking and structural questions,
                    executed in the database's READ-mode sandbox; errors are fed
                    back so the model can correct its own query

Every step is emitted as an event (for a live reasoning trace in the UI),
passages are numbered as they are retrieved so the answer can cite them as
[n], and the entities the agent touched are returned so the UI can light up
the part of the graph the answer came from.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator
from typing import Any

import anthropic
from pydantic import BaseModel, Field, ValidationError

from app.config import settings
from app.models import GraphResponse
from app.services.embeddings import Embedder, embed_async, get_embedder
from app.services.graph_store import GraphStore, ReadOnlyViolation

logger = logging.getLogger(__name__)

MAX_STEPS = 8
MAX_TOOL_RESULT_CHARS = 12_000
CYPHER_ROW_LIMIT = 50

GRAPH_SCHEMA = """Graph schema (Neo4j):
(:Document {id, filename, status, page_count, created_at})
(:Chunk {id, text, page_number, document_id, document_name})            -- source passages
(:Entity {id, name, type, description, aliases, document_ids})
   type is one of PERSON, ORGANIZATION, LOCATION, CONCEPT, EVENT, TECHNOLOGY, PRODUCT, OTHER
(:Community {id, level, title, summary, findings, size})                -- topic clusters; level 1 = broad, 0 = sub-topic
(:Entity)-[:RELATES {type, description, confidence, document_id}]->(:Entity)
   The relationship verb (e.g. FOUNDED, PART_OF) is the `type` PROPERTY of :RELATES, not the relationship type.
(:Entity)-[:MENTIONED_IN]->(:Chunk)
(:Document)-[:HAS_CHUNK]->(:Chunk)
(:Entity)-[:IN_COMMUNITY]->(:Community)
(:Community)-[:PART_OF]->(:Community)"""

SYSTEM_PROMPT = f"""You answer questions about the user's documents using a knowledge graph built from them.

Plan your retrieval before answering:
- Specific facts: search_passages, then explore_entities around the entities involved when
  the answer depends on how things connect (multi-hop questions).
- Broad questions about themes, main topics or the corpus as a whole: start with search_topics.
- Counting, ranking, listing or structural questions ("which person is connected to the most
  organizations?"): write a run_cypher query. If it errors, read the error and fix the query.
- Use search_entities to find the exact node for a name before exploring it.
Make independent tool calls in parallel. Stop retrieving once you have enough evidence.

Answer using only what the tools returned. Cite passages inline as [n] using the numbers that
search_passages assigned; cite every factual claim that comes from a passage. If the documents
don't contain the answer, say so plainly. Write clear, concise prose; use a short list only when
the answer is naturally a list.

{GRAPH_SCHEMA}"""


# ── Tool input schemas (validated before execution) ───────────────────────────


class SearchPassages(BaseModel):
    query: str = Field(description="What to look for, phrased as a search query.")
    top_k: int = Field(default=6, ge=1, le=12, description="Number of passages (1-12).")


class SearchEntities(BaseModel):
    query: str = Field(description="Entity name or description to look up.")


class ExploreEntities(BaseModel):
    entity_ids: list[str] = Field(description="Entity ids from search_entities (1-10).")
    depth: int = Field(default=1, ge=1, le=2, description="Hops to expand (1-2).")


class SearchTopics(BaseModel):
    query: str = Field(description="Theme or question to find relevant topic clusters for.")
    top_k: int = Field(default=4, ge=1, le=8)


class RunCypher(BaseModel):
    cypher: str = Field(description="A single read-only Cypher query. Always include a LIMIT.")
    purpose: str = Field(description="One short sentence: what this query finds.")


TOOL_MODELS: dict[str, type[BaseModel]] = {
    "search_passages": SearchPassages,
    "search_entities": SearchEntities,
    "explore_entities": ExploreEntities,
    "search_topics": SearchTopics,
    "run_cypher": RunCypher,
}

TOOL_DESCRIPTIONS = {
    "search_passages": "Semantic search over source passages from the documents. Returns numbered "
    "passages [n] with document and page; these numbers are what you cite.",
    "search_entities": "Find graph entities by name or description (hybrid full-text + semantic). "
    "Returns ids, types, descriptions and how connected each entity is.",
    "explore_entities": "Expand the knowledge graph around entities: returns their relationships "
    "(subject -[VERB]-> object) up to `depth` hops away.",
    "search_topics": "Search community reports: summaries of clusters of related entities across all "
    "documents. Best for broad, thematic or corpus-level questions.",
    "run_cypher": "Run a read-only Cypher query against the graph (writes are rejected by the "
    f"database). At most {CYPHER_ROW_LIMIT} rows are returned.\n\n{GRAPH_SCHEMA}",
}


def tool_definitions() -> list[dict[str, Any]]:
    tools = []
    for name, model in TOOL_MODELS.items():
        schema = model.model_json_schema()
        schema.pop("title", None)
        for prop in schema.get("properties", {}).values():
            # Strict tool schemas don't take these keywords; Pydantic still enforces them.
            for key in ("title", "default", "minimum", "maximum", "minItems", "maxItems"):
                prop.pop(key, None)
        schema["additionalProperties"] = False
        schema["required"] = list(schema.get("properties", {}).keys())
        tools.append(
            {
                "name": name,
                "description": TOOL_DESCRIPTIONS[name],
                "input_schema": schema,
                "strict": True,
            }
        )
    return tools


def _clip(text: str, limit: int = MAX_TOOL_RESULT_CHARS) -> str:
    return text if len(text) <= limit else text[:limit] + "\n…[truncated]"


class AgentRun:
    """State for one question: numbered sources and the entities touched."""

    def __init__(self) -> None:
        self.sources: list[dict[str, Any]] = []  # index = citation number - 1
        self._source_index: dict[str, int] = {}
        self.entity_ids: list[str] = []
        self.steps: list[dict[str, Any]] = []

    def cite(self, hit: dict[str, Any]) -> int:
        cid = hit["chunk_id"]
        if cid not in self._source_index:
            self.sources.append(
                {
                    "chunk_id": cid,
                    "text": hit["text"],
                    "page_number": hit["page_number"],
                    "document_name": hit["document_name"],
                    "similarity_score": float(hit.get("score", 0.0)),
                }
            )
            self._source_index[cid] = len(self.sources)
        return self._source_index[cid]

    def touch(self, ids: list[str]) -> None:
        for i in ids:
            if i and i not in self.entity_ids:
                self.entity_ids.append(i)


class GraphRAGAgent:
    def __init__(
        self,
        graph_store: GraphStore,
        client: anthropic.AsyncAnthropic | None = None,
        embedder: Embedder | None = None,
        max_steps: int = MAX_STEPS,
    ) -> None:
        self._gs = graph_store
        self._llm = client or anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key or None)
        self._embedder = embedder
        self._max_steps = max_steps
        self._tools = tool_definitions()

    # ── Public API ────────────────────────────────────────────────────────────

    async def run(self, question: str, document_id: str | None = None) -> AsyncIterator[dict[str, Any]]:
        """Answer `question`, yielding events: step, step_result, text, done (or error)."""
        run = AgentRun()
        started = time.monotonic()
        messages: list[dict[str, Any]] = [{"role": "user", "content": question}]
        scope = (
            "\n\nThe user is asking about one specific document; search_passages is already restricted to it."
            if document_id
            else ""
        )
        answer_parts: list[str] = []
        usage = {"input_tokens": 0, "output_tokens": 0}

        for turn in range(self._max_steps + 1):
            final_turn = turn == self._max_steps
            if final_turn:
                messages.append(
                    {"role": "user", "content": "Retrieval budget reached. Answer now with what you have."}
                )
            turn_text: list[str] = []
            try:
                async with self._stream(messages, scope, tools_enabled=not final_turn) as stream:
                    async for event in stream:
                        if event.type == "text":
                            turn_text.append(event.text)
                            yield {"type": "text", "delta": event.text}
                    message = await stream.get_final_message()
            except anthropic.APIError as exc:
                logger.exception("Agent LLM call failed")
                yield {"type": "error", "message": f"Claude API error: {getattr(exc, 'message', exc)}"}
                return

            usage["input_tokens"] += getattr(message.usage, "input_tokens", 0) or 0
            usage["output_tokens"] += getattr(message.usage, "output_tokens", 0) or 0
            answer_parts.extend(turn_text)

            if message.stop_reason == "refusal":
                yield {"type": "error", "message": "Claude declined to answer this question."}
                return

            tool_uses = [b for b in message.content if b.type == "tool_use"]
            messages.append({"role": "assistant", "content": message.content})
            if not tool_uses or message.stop_reason != "tool_use":
                break

            if turn_text:
                # Narration between tool calls is not part of the final answer.
                answer_parts = []
                yield {"type": "text_reset"}

            results = []
            for block in tool_uses:
                step = {"type": "step", "id": block.id, "tool": block.name, "input": block.input}
                run.steps.append(step)
                yield step
                content, summary, is_error = await self._execute(block.name, block.input, run, document_id)
                yield {
                    "type": "step_result",
                    "id": block.id,
                    "summary": summary,
                    "is_error": is_error,
                }
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": _clip(content),
                        **({"is_error": True} if is_error else {}),
                    }
                )
            messages.append({"role": "user", "content": results})

        graph = await self._highlight_graph(run)
        yield {
            "type": "done",
            "answer": "".join(answer_parts).strip(),
            "sources": run.sources,
            "graph": graph.model_dump(),
            "highlight_ids": run.entity_ids[:40],
            "steps": len(run.steps),
            "latency_ms": int((time.monotonic() - started) * 1000),
            "usage": usage,
        }

    async def answer(self, question: str, document_id: str | None = None) -> dict[str, Any]:
        """Non-streaming convenience wrapper: returns the final `done` event."""
        async for event in self.run(question, document_id):
            if event["type"] in ("done", "error"):
                return event
        return {"type": "error", "message": "Agent ended without an answer."}

    # ── LLM call ──────────────────────────────────────────────────────────────

    def _stream(self, messages: list[dict[str, Any]], scope: str, tools_enabled: bool):
        kwargs: dict[str, Any] = dict(
            model=settings.llm_model,
            max_tokens=32000,
            system=SYSTEM_PROMPT + scope,
            messages=messages,
            tools=self._tools,
            tool_choice={"type": "auto"} if tools_enabled else {"type": "none"},
            output_config={"effort": settings.answer_effort},
            cache_control={"type": "ephemeral"},
        )
        if settings.llm_fallbacks:
            return self._llm.beta.messages.stream(
                betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs
            )
        kwargs.pop("cache_control")
        return self._llm.messages.stream(**kwargs)

    # ── Tools ─────────────────────────────────────────────────────────────────

    async def _embed(self, text: str):
        return (await embed_async([text], self._embedder or get_embedder()))[0]

    async def _execute(
        self, name: str, raw_input: Any, run: AgentRun, document_id: str | None
    ) -> tuple[str, str, bool]:
        """Returns (content for Claude, one-line summary for the UI, is_error)."""
        model = TOOL_MODELS.get(name)
        if model is None:
            return f"Unknown tool {name}", f"Unknown tool {name}", True
        try:
            args = model.model_validate(raw_input)
        except ValidationError as exc:
            return f"Invalid input: {exc}", "Invalid tool input", True
        try:
            handler = getattr(self, f"_tool_{name}")
            return await handler(args, run, document_id)
        except ReadOnlyViolation:
            return (
                "Rejected: the database only allows read-only queries.",
                "Query rejected (read-only)",
                True,
            )
        except Exception as exc:  # noqa: BLE001 - errors go back to the model to self-correct
            msg = getattr(exc, "message", None) or str(exc)
            return f"Error: {msg}", f"Error: {msg[:120]}", True

    async def _tool_search_passages(self, a: SearchPassages, run: AgentRun, doc: str | None):
        hits = await self._gs.search_chunks(await self._embed(a.query), k=a.top_k, document_id=doc)
        if not hits:
            return "No passages found.", "No passages found", False
        chunk_ids = [h["chunk_id"] for h in hits]
        run.touch(await self._gs.get_entities_for_chunks(chunk_ids, limit=8))
        parts = []
        for h in hits:
            n = run.cite(h)
            parts.append(f"[{n}] {h['document_name']}, page {h['page_number']}\n{h['text']}")
        return "\n\n".join(parts), f"Found {len(hits)} passages", False

    async def _tool_search_entities(self, a: SearchEntities, run: AgentRun, doc: str | None):
        rows = await self._gs.search_entities(a.query, await self._embed(a.query), k=8)
        if not rows:
            return "No matching entities.", "No matching entities", False
        run.touch([r["id"] for r in rows[:3]])
        lines = [
            f"- id={r['id']} | {r['name']} ({r['type']}, {r['degree']} connections)"
            + (f": {r['description']}" if r["description"] else "")
            + (f" | aka {', '.join(r['aliases'])}" if r.get("aliases") else "")
            for r in rows
        ]
        return "\n".join(lines), f"Matched {', '.join(r['name'] for r in rows[:3])}", False

    async def _tool_explore_entities(self, a: ExploreEntities, run: AgentRun, doc: str | None):
        graph = await self._gs.get_neighbourhoods(a.entity_ids[:10], a.depth)
        if not graph.nodes:
            return "No such entities.", "Nothing to expand", True
        run.touch(a.entity_ids)
        run.touch([n.id for n in graph.nodes][:25])
        names = {n.id: n.name for n in graph.nodes}
        lines = [f"Entities: {', '.join(f'{n.name} ({n.type})' for n in graph.nodes[:60])}", "Relationships:"]
        lines += [
            f"- {names.get(e.source, e.source)} -[{e.type}]-> {names.get(e.target, e.target)}"
            + (f": {e.description}" if e.description else "")
            for e in graph.edges[:120]
        ]
        return (
            "\n".join(lines),
            f"Explored {len(graph.nodes)} entities, {len(graph.edges)} relationships",
            False,
        )

    async def _tool_search_topics(self, a: SearchTopics, run: AgentRun, doc: str | None):
        rows = await self._gs.search_communities(await self._embed(a.query), k=a.top_k)
        if not rows:
            return (
                "No topic reports exist yet (too few connected entities).",
                "No topic reports yet",
                False,
            )
        for r in rows[:2]:
            run.touch(r["member_ids"][:10])
        parts = []
        for r in rows:
            findings = "\n".join(f"  - {f}" for f in (r["findings"] or []))
            parts.append(
                f"## {r['title']} (level {r['level']}, {r['size']} entities; key: "
                f"{', '.join(r['top_entities'])})\n{r['summary']}\n{findings}"
            )
        return "\n\n".join(parts), f"Read {len(rows)} topic reports", False

    async def _tool_run_cypher(self, a: RunCypher, run: AgentRun, doc: str | None):
        rows = await self._gs.execute_read_only(a.cypher)
        rows = rows[:CYPHER_ROW_LIMIT]
        for row in rows:
            for v in row.values():
                if isinstance(v, dict) and "id" in v and "Entity" in v.get("_labels", []):
                    run.touch([v["id"]])
        body = json.dumps(rows, default=str, ensure_ascii=False)
        return body if rows else "[] (no rows)", f"{a.purpose} → {len(rows)} rows", False

    async def _highlight_graph(self, run: AgentRun) -> GraphResponse:
        if not run.entity_ids:
            return GraphResponse(nodes=[], edges=[])
        try:
            return await self._gs.get_neighbourhoods(run.entity_ids[:15], 1)
        except Exception:  # noqa: BLE001 - highlighting is best-effort
            logger.exception("Highlight graph failed")
            return GraphResponse(nodes=[], edges=[])
