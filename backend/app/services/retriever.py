"""Hybrid retrieval: vector search + graph traversal + LLM answer generation."""

import logging

import anthropic

from app.config import settings
from app.models import GraphResponse, QueryRequest, QueryResponse, SourceChunk
from app.services.graph_store import GraphStore
from app.services.vector_store import VectorStore

logger = logging.getLogger(__name__)

_ANSWER_SYSTEM = """You are a knowledge graph question-answering assistant.
You have access to:
1. Retrieved text chunks (most relevant passages from the source documents).
2. A subgraph of entities and relationships related to the query.

Answer the user's question thoroughly and accurately, citing which sources informed your answer.
If the answer is not supported by the provided context, say so clearly.
Format your response in clear paragraphs. When referencing a source, mention the document name and page number."""


class Retriever:
    def __init__(self, vector_store: VectorStore, graph_store: GraphStore) -> None:
        self._vs = vector_store
        self._gs = graph_store
        self._llm = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    def query(self, request: QueryRequest) -> QueryResponse:
        # 1. Vector search
        hits = self._vs.search(
            query=request.query,
            top_k=request.top_k,
            document_id=request.document_id,
        )

        sources = [
            SourceChunk(
                chunk_id=h["chunk_id"],
                text=h["text"],
                page_number=h["page_number"],
                document_name=h["document_name"],
                similarity_score=h["similarity_score"],
            )
            for h in hits
        ]

        # 2. Find entities mentioned in the retrieved chunks
        chunk_ids = [h["chunk_id"] for h in hits]
        entity_ids = self._gs.get_entities_for_chunks(chunk_ids)

        # 3. Graph traversal: expand entity neighbourhoods
        graph_nodes: dict[str, object] = {}
        graph_edges: dict[str, object] = {}

        for eid in entity_ids[:10]:  # cap to avoid explosion
            subgraph = self._gs.get_entity_neighbourhood(eid, hop_depth=request.hop_depth)
            for node in subgraph.nodes:
                graph_nodes[node.id] = node
            for edge in subgraph.edges:
                graph_edges[edge.id] = edge

        combined_graph = GraphResponse(
            nodes=list(graph_nodes.values()),
            edges=list(graph_edges.values()),
        )

        # 4. Build context for LLM
        context = self._build_context(request.query, sources, combined_graph)

        # 5. Generate answer
        answer = self._generate_answer(request.query, context)

        cypher = (
            f"MATCH (e:Entity)-[:MENTIONED_IN]->(c:Chunk) WHERE c.id IN {chunk_ids!r} RETURN e LIMIT 20"
            if chunk_ids else None
        )

        return QueryResponse(
            answer=answer,
            sources=sources,
            graph_context=combined_graph,
            cypher_used=cypher,
        )

    # ------------------------------------------------------------------

    def _build_context(
        self,
        query: str,
        sources: list[SourceChunk],
        graph: GraphResponse,
    ) -> str:
        parts: list[str] = []

        if sources:
            parts.append("=== RETRIEVED TEXT CHUNKS ===")
            for i, s in enumerate(sources, 1):
                parts.append(
                    f"[{i}] (doc: {s.document_name}, page {s.page_number}, "
                    f"similarity: {s.similarity_score:.3f})\n{s.text}"
                )

        if graph.nodes:
            parts.append("\n=== RELATED ENTITIES ===")
            for node in graph.nodes[:30]:
                desc = f" — {node.description}" if node.description else ""
                parts.append(f"• {node.name} ({node.type}){desc}")

        if graph.edges:
            parts.append("\n=== RELATIONSHIPS ===")
            node_map = {n.id: n.name for n in graph.nodes}
            for edge in graph.edges[:50]:
                src = node_map.get(edge.source, edge.source)
                tgt = node_map.get(edge.target, edge.target)
                desc = f" — {edge.description}" if edge.description else ""
                parts.append(
                    f"• {src} --[{edge.type} conf={edge.confidence:.2f}]--> {tgt}{desc}"
                )

        return "\n".join(parts)

    def _generate_answer(self, query: str, context: str) -> str:
        message = self._llm.messages.create(
            model=settings.llm_model,
            max_tokens=2048,
            system=_ANSWER_SYSTEM,
            messages=[
                {
                    "role": "user",
                    "content": f"Question: {query}\n\n{context}",
                }
            ],
        )
        return message.content[0].text
