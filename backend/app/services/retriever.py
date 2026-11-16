"""Hybrid retrieval: Neo4j vector search + graph expansion + grounded LLM answer."""

from __future__ import annotations

import logging

import anthropic

from app.config import settings
from app.models import GraphResponse, QueryRequest, QueryResponse, SourceChunk
from app.services.embeddings import Embedder, embed_async, get_embedder
from app.services.graph_store import GraphStore

logger = logging.getLogger(__name__)

ANSWER_SYSTEM = """You answer questions about a user's documents using a knowledge graph.

You receive numbered source passages retrieved from the documents and a subgraph of
related entities and relationships. Answer using only that context. Cite passages
inline as [1], [2], etc., matching their numbers. If the context does not support an
answer, say so plainly rather than guessing. Write in clear, concise paragraphs."""


class Retriever:
    def __init__(
        self,
        graph_store: GraphStore,
        client: anthropic.AsyncAnthropic | None = None,
        embedder: Embedder | None = None,
    ) -> None:
        self._gs = graph_store
        self._llm = client or anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key or None)
        self._embedder = embedder

    async def query(self, request: QueryRequest) -> QueryResponse:
        # 1. Semantic search over chunk embeddings (Neo4j vector index)
        qvec = (await embed_async([request.query], self._embedder or get_embedder()))[0]
        hits = await self._gs.search_chunks(qvec, k=request.top_k, document_id=request.document_id)
        sources = [
            SourceChunk(
                chunk_id=h["chunk_id"],
                text=h["text"],
                page_number=h["page_number"],
                document_name=h["document_name"],
                similarity_score=float(h["score"]),
            )
            for h in hits
        ]

        # 2. Entities mentioned in those chunks → 3. expand their neighbourhoods
        entity_ids = await self._gs.get_entities_for_chunks([s.chunk_id for s in sources])
        graph = (
            await self._gs.get_neighbourhoods(entity_ids, request.hop_depth)
            if entity_ids
            else GraphResponse(nodes=[], edges=[])
        )

        # 4. Grounded answer
        answer = (
            await self._answer(request.query, self.build_context(sources, graph))
            if sources
            else ("I couldn't find anything relevant in your documents yet. Try uploading a PDF first.")
        )
        return QueryResponse(
            answer=answer,
            sources=sources,
            graph_context=graph,
            cypher_used=GraphStore.CHUNK_SEARCH_CYPHER,
        )

    @staticmethod
    def build_context(sources: list[SourceChunk], graph: GraphResponse) -> str:
        parts: list[str] = []
        if sources:
            parts.append("<sources>")
            for i, s in enumerate(sources, 1):
                parts.append(
                    f'<source id="{i}" document="{s.document_name}" page="{s.page_number}">\n{s.text}\n</source>'
                )
            parts.append("</sources>")
        if graph.nodes:
            names = {n.id: n.name for n in graph.nodes}
            parts.append("<entities>")
            parts.extend(
                f"- {n.name} ({n.type})" + (f": {n.description}" if n.description else "")
                for n in graph.nodes[:40]
            )
            parts.append("</entities>")
            if graph.edges:
                parts.append("<relationships>")
                parts.extend(
                    f"- {names.get(e.source, e.source)} -[{e.type}]-> {names.get(e.target, e.target)}"
                    + (f": {e.description}" if e.description else "")
                    for e in graph.edges[:60]
                )
                parts.append("</relationships>")
        return "\n".join(parts)

    async def _answer(self, query: str, context: str) -> str:
        kwargs: dict = dict(
            model=settings.llm_model,
            max_tokens=16000,
            system=ANSWER_SYSTEM,
            messages=[{"role": "user", "content": f"{context}\n\n<question>{query}</question>"}],
            output_config={"effort": settings.answer_effort},
        )
        if settings.llm_fallbacks:
            msg = await self._llm.beta.messages.create(
                betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs
            )
        else:
            msg = await self._llm.messages.create(**kwargs)
        if msg.stop_reason == "refusal":
            return "I can't answer that question from these documents."
        return "".join(b.text for b in msg.content if b.type == "text").strip()
