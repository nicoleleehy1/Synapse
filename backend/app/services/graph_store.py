"""Neo4j persistence layer (async driver).

Neo4j is the single source of truth for the whole system:
  (:Document)  ingestion jobs and their live status
  (:Chunk)     source passages, with a native vector index on `embedding`
  (:Entity)    knowledge-graph nodes, with a vector index and a full-text index
  -[:RELATES]-> typed relationships between entities
  -[:MENTIONED_IN]-> entity ↔ chunk provenance
  -[:HAS_CHUNK]-> document ↔ chunk

Keeping vectors in Neo4j (rather than a local FAISS file) makes the API
process stateless, so it can be redeployed or scaled horizontally freely.

All bulk writes use UNWIND so a document is persisted in a handful of round
trips instead of one query per row.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
from neo4j import READ_ACCESS, AsyncDriver, AsyncGraphDatabase, Query
from neo4j.exceptions import ClientError
from neo4j.graph import Node, Path
from neo4j.graph import Relationship as Neo4jRel

from app.config import settings
from app.models import (
    DocumentStatus,
    Entity,
    GraphEdge,
    GraphNode,
    GraphResponse,
    Relationship,
    TextChunk,
)

logger = logging.getLogger(__name__)

_HIDDEN_PROPS = {"embedding"}
_WRITE_BATCH = 500
_WRITE_REJECTED_CODES = {
    "Neo.ClientError.Statement.AccessMode",
    "Neo.ClientError.Security.Forbidden",
}


class ReadOnlyViolation(Exception):
    """Raised when a user-supplied query attempts to write."""


class GraphStore:
    def __init__(self, driver: AsyncDriver | None = None) -> None:
        self._driver: AsyncDriver | None = driver
        self._db = settings.neo4j_database

    # ------------------------------------------------------------------
    # Lifecycle / schema
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        if self._driver is None:
            if not settings.neo4j_password:
                raise RuntimeError("NEO4J_PASSWORD is not set")
            self._driver = AsyncGraphDatabase.driver(
                settings.neo4j_uri,
                auth=(settings.neo4j_user, settings.neo4j_password),
                notifications_min_severity="WARNING",
            )
        await self._driver.verify_connectivity()
        await self.ensure_schema()
        logger.info("Connected to Neo4j at %s", settings.neo4j_uri)

    async def close(self) -> None:
        if self._driver:
            await self._driver.close()

    async def ping(self) -> bool:
        try:
            await self._run("RETURN 1")
            return True
        except Exception:  # noqa: BLE001
            return False

    async def ensure_schema(self) -> None:
        dim = int(settings.embedding_dim)
        statements = [
            "CREATE CONSTRAINT entity_id IF NOT EXISTS FOR (e:Entity) REQUIRE e.id IS UNIQUE",
            "CREATE CONSTRAINT chunk_id IF NOT EXISTS FOR (c:Chunk) REQUIRE c.id IS UNIQUE",
            "CREATE CONSTRAINT document_id IF NOT EXISTS FOR (d:Document) REQUIRE d.id IS UNIQUE",
            "CREATE INDEX entity_document IF NOT EXISTS FOR (e:Entity) ON (e.document_id)",
            "CREATE INDEX chunk_document IF NOT EXISTS FOR (c:Chunk) ON (c.document_id)",
            "CREATE FULLTEXT INDEX entity_names IF NOT EXISTS FOR (e:Entity) ON EACH [e.name, e.description]",
            (
                "CREATE VECTOR INDEX chunk_embedding IF NOT EXISTS FOR (c:Chunk) ON c.embedding "
                f"OPTIONS {{indexConfig: {{`vector.dimensions`: {dim}, `vector.similarity_function`: 'cosine'}}}}"
            ),
            (
                "CREATE VECTOR INDEX entity_embedding IF NOT EXISTS FOR (e:Entity) ON e.embedding "
                f"OPTIONS {{indexConfig: {{`vector.dimensions`: {dim}, `vector.similarity_function`: 'cosine'}}}}"
            ),
            "CREATE CONSTRAINT community_id IF NOT EXISTS FOR (c:Community) REQUIRE c.id IS UNIQUE",
            (
                "CREATE VECTOR INDEX community_embedding IF NOT EXISTS FOR (c:Community) ON c.embedding "
                f"OPTIONS {{indexConfig: {{`vector.dimensions`: {dim}, `vector.similarity_function`: 'cosine'}}}}"
            ),
            # Migration: entities may now belong to several documents.
            (
                "MATCH (e:Entity) WHERE e.document_ids IS NULL "
                "SET e.document_ids = CASE WHEN e.document_id IS NULL THEN [] ELSE [e.document_id] END"
            ),
        ]
        for stmt in statements:
            await self._run(stmt)

    # ------------------------------------------------------------------
    # Documents (ingestion jobs)
    # ------------------------------------------------------------------

    async def save_document(self, status: DocumentStatus) -> None:
        await self._run(
            "MERGE (d:Document {id: $id}) SET d += $props",
            id=status.document_id,
            props=status.model_dump(exclude={"document_id"}, exclude_none=True),
        )

    async def get_document(self, document_id: str) -> DocumentStatus | None:
        rows = await self._run("MATCH (d:Document {id: $id}) RETURN d", id=document_id)
        return self._to_status(rows[0]["d"]) if rows else None

    async def list_documents(self) -> list[DocumentStatus]:
        rows = await self._run("MATCH (d:Document) RETURN d ORDER BY d.created_at DESC")
        return [self._to_status(r["d"]) for r in rows]

    async def fail_interrupted_documents(self) -> int:
        """Mark jobs left mid-flight by a previous process as failed."""
        rows = await self._run(
            """
            MATCH (d:Document) WHERE d.status IN ['queued', 'processing']
            SET d.status = 'error', d.error = 'Interrupted by a server restart. Please re-upload.'
            RETURN count(d) AS n
            """
        )
        return rows[0]["n"] if rows else 0

    # ------------------------------------------------------------------
    # Bulk ingestion writes
    # ------------------------------------------------------------------

    async def write_chunks(self, chunks: list[TextChunk], embeddings: np.ndarray) -> None:
        rows = [
            {
                "id": c.id,
                "text": c.text,
                "page_number": c.page_number,
                "document_id": c.document_id,
                "document_name": c.document_name,
                "token_count": c.token_count,
                "embedding": embeddings[i].tolist(),
            }
            for i, c in enumerate(chunks)
        ]
        for batch in _batches(rows):
            await self._run(
                """
                UNWIND $rows AS row
                MERGE (c:Chunk {id: row.id})
                SET c.text = row.text, c.page_number = row.page_number,
                    c.document_id = row.document_id, c.document_name = row.document_name,
                    c.token_count = row.token_count
                WITH c, row
                CALL db.create.setNodeVectorProperty(c, 'embedding', row.embedding)
                WITH c, row
                MATCH (d:Document {id: row.document_id})
                MERGE (d)-[:HAS_CHUNK]->(c)
                """,
                rows=batch,
            )

    async def write_graph(
        self,
        entities: list[Entity],
        entity_embeddings: list[np.ndarray | None],
        relationships: list[Relationship],
    ) -> None:
        ent_rows = [
            {
                "id": e.id,
                "name": e.name,
                "type": e.type,
                "description": e.description or "",
                "source_document": e.source_document,
                "document_id": e.document_id,
                "document_ids": [e.document_id] if e.document_id else [],
                "aliases": e.aliases,
                "chunk_ids": e.source_chunk_ids,
                "embedding": vec.tolist() if vec is not None else None,
            }
            for e, vec in zip(entities, entity_embeddings, strict=True)
        ]
        for batch in _batches(ent_rows):
            await self._run(
                """
                UNWIND $rows AS row
                MERGE (e:Entity {id: row.id})
                ON CREATE SET e.name = row.name, e.type = row.type, e.description = row.description,
                    e.source_document = row.source_document, e.document_id = row.document_id,
                    e.aliases = [], e.source_chunk_ids = [], e.document_ids = [], e.new = true
                // Existing entity (cross-document match): union provenance, keep its identity.
                WITH e, row, row.aliases + CASE WHEN row.name <> e.name THEN [row.name] ELSE [] END AS names
                SET e.aliases = e.aliases + [a IN names WHERE NOT a IN e.aliases AND a <> e.name],
                    e.source_chunk_ids = e.source_chunk_ids + [c IN row.chunk_ids WHERE NOT c IN e.source_chunk_ids],
                    e.document_ids = e.document_ids + [d IN row.document_ids WHERE NOT d IN e.document_ids],
                    e.description = CASE WHEN coalesce(e.description, '') = '' THEN row.description
                                         ELSE e.description END
                WITH e, row, coalesce(e.new, false) AS created
                REMOVE e.new
                WITH e, row, created
                CALL (e, row, created) {
                    WITH e, row, created WHERE row.embedding IS NOT NULL AND created
                    CALL db.create.setNodeVectorProperty(e, 'embedding', row.embedding)
                }
                WITH e, row
                UNWIND row.chunk_ids AS cid
                MATCH (c:Chunk {id: cid})
                MERGE (e)-[:MENTIONED_IN]->(c)
                """,
                rows=batch,
            )

        rel_rows = [
            {
                "id": r.id,
                "src": r.source_entity_id,
                "tgt": r.target_entity_id,
                "type": r.type,
                "description": r.description or "",
                "confidence": r.confidence,
                "chunk_id": r.source_chunk_id,
                "source_document": r.source_document,
                "document_id": r.document_id,
            }
            for r in relationships
        ]
        for batch in _batches(rel_rows):
            await self._run(
                """
                UNWIND $rows AS row
                MATCH (src:Entity {id: row.src}), (tgt:Entity {id: row.tgt})
                MERGE (src)-[r:RELATES {id: row.id}]->(tgt)
                SET r.type = row.type, r.description = row.description,
                    r.confidence = row.confidence, r.source_chunk_id = row.chunk_id,
                    r.source_document = row.source_document, r.document_id = row.document_id
                """,
                rows=batch,
            )

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    CHUNK_SEARCH_CYPHER = """
CALL db.index.vector.queryNodes('chunk_embedding', $candidates, $vector) YIELD node, score
WHERE $document_id IS NULL OR node.document_id = $document_id
RETURN node.id AS chunk_id, node.text AS text, node.page_number AS page_number,
       node.document_id AS document_id, node.document_name AS document_name, score
ORDER BY score DESC LIMIT $k""".strip()

    async def search_chunks(
        self, vector: np.ndarray, k: int, document_id: str | None = None
    ) -> list[dict[str, Any]]:
        # Over-fetch when filtering by document: the vector index is global.
        candidates = k * 8 if document_id else k
        return await self._run(
            self.CHUNK_SEARCH_CYPHER,
            vector=vector.tolist(),
            candidates=candidates,
            k=k,
            document_id=document_id,
        )

    async def get_entities_for_chunks(self, chunk_ids: list[str], limit: int = 10) -> list[str]:
        """Entities mentioned in the given chunks, most-mentioned first."""
        rows = await self._run(
            """
            MATCH (e:Entity)-[:MENTIONED_IN]->(c:Chunk) WHERE c.id IN $chunk_ids
            RETURN e.id AS eid, count(c) AS hits ORDER BY hits DESC LIMIT $limit
            """,
            chunk_ids=chunk_ids,
            limit=limit,
        )
        return [r["eid"] for r in rows]

    async def get_full_graph(self, document_id: str | None = None, limit: int = 2000) -> GraphResponse:
        rows = await self._run(
            """
            MATCH (e:Entity)
            WHERE $doc IS NULL OR $doc IN e.document_ids
            WITH e LIMIT $limit
            WITH collect(e) AS ents
            UNWIND ents AS e
            OPTIONAL MATCH (e)-[r:RELATES]->(t:Entity) WHERE t IN ents
            RETURN e, collect({r: r, tgt: t.id}) AS rels
            """,
            doc=document_id,
            limit=limit,
        )
        nodes, edges = [], []
        for row in rows:
            node = self._to_node(row["e"])
            nodes.append(node)
            for rel in row["rels"]:
                if rel["r"] is not None:
                    edges.append(self._to_edge(rel["r"], node.id, rel["tgt"]))
        return GraphResponse(nodes=nodes, edges=edges)

    async def get_entity_neighbourhood(self, entity_id: str, hop_depth: int = 2) -> GraphResponse:
        return await self.get_neighbourhoods([entity_id], hop_depth)

    async def get_neighbourhoods(self, entity_ids: list[str], hop_depth: int = 2) -> GraphResponse:
        # Variable-length bounds cannot be query parameters in Cypher, so the
        # (validated, integer) depth is interpolated.
        depth = max(1, min(3, int(hop_depth)))
        rows = await self._run(
            f"""
            MATCH (start:Entity) WHERE start.id IN $ids
            OPTIONAL MATCH path = (start)-[:RELATES*1..{depth}]-(:Entity)
            WITH collect(DISTINCT start) AS starts, collect(path) AS paths
            WITH starts,
                 [p IN paths | nodes(p)] AS node_lists,
                 [p IN paths | relationships(p)] AS rel_lists
            WITH starts + reduce(acc = [], l IN node_lists | acc + l) AS ns,
                 reduce(acc = [], l IN rel_lists | acc + l) AS rs
            UNWIND ns AS n
            WITH collect(DISTINCT n) AS ns, rs
            UNWIND (CASE WHEN rs = [] THEN [null] ELSE rs END) AS r
            WITH ns, collect(DISTINCT r) AS rs
            RETURN ns,
                   [r IN rs | {{r: r, src: startNode(r).id, tgt: endNode(r).id}}] AS rs
            """,
            ids=entity_ids,
        )
        if not rows:
            return GraphResponse(nodes=[], edges=[])
        row = rows[0]
        return GraphResponse(
            nodes=[self._to_node(n) for n in row["ns"]],
            edges=[self._to_edge(x["r"], x["src"], x["tgt"]) for x in row["rs"]],
        )

    # ------------------------------------------------------------------
    # User-supplied Cypher (read-only sandbox)
    # ------------------------------------------------------------------

    async def execute_read_only(self, cypher: str, params: dict | None = None) -> list[dict]:
        """Run arbitrary Cypher in a READ-mode session with a timeout and row cap.

        Neo4j itself rejects any write (CREATE/MERGE/SET/DELETE, write procedures,
        schema changes) in a read transaction, so this is enforced by the database
        rather than by string matching.
        """
        assert self._driver is not None
        out: list[dict] = []
        try:
            async with self._driver.session(database=self._db, default_access_mode=READ_ACCESS) as s:
                result = await s.run(Query(cypher, timeout=settings.cypher_timeout_s), params or {})
                async for record in result:
                    out.append({k: _jsonable(v) for k, v in record.items()})
                    if len(out) >= settings.cypher_max_rows:
                        break
                await result.consume()
        except ClientError as exc:
            if exc.code in _WRITE_REJECTED_CODES:
                raise ReadOnlyViolation(exc.message or str(exc)) from exc
            raise
        return out

    # ------------------------------------------------------------------
    # Deletes
    # ------------------------------------------------------------------

    async def delete_document(self, document_id: str) -> None:
        # Entities shared with other documents survive; they just lose this provenance.
        await self._run("MATCH ()-[r:RELATES {document_id: $doc}]->() DELETE r", doc=document_id)
        await self._run(
            """
            MATCH (e:Entity) WHERE $doc IN e.document_ids
            SET e.document_ids = [d IN e.document_ids WHERE d <> $doc]
            WITH e WHERE size(e.document_ids) = 0
            DETACH DELETE e
            """,
            doc=document_id,
        )
        await self._run("MATCH (c:Chunk {document_id: $doc}) DETACH DELETE c", doc=document_id)
        await self._run("MATCH (d:Document {id: $doc}) DETACH DELETE d", doc=document_id)

    # ------------------------------------------------------------------
    # Cross-document entity resolution
    # ------------------------------------------------------------------

    async def match_existing_entities(
        self, rows: list[dict[str, Any]], threshold: float, exclude_document: str | None
    ) -> dict[int, str]:
        """For each {idx, type, embedding}, the id of the most similar existing entity of the
        same type (cosine >= threshold) from *other* documents."""
        if not rows:
            return {}
        out = await self._run(
            """
            UNWIND $rows AS row
            CALL (row) {
                CALL db.index.vector.queryNodes('entity_embedding', 5, row.embedding) YIELD node, score
                WHERE node.type = row.type AND score >= $threshold
                  AND ($exclude IS NULL OR NOT $exclude IN node.document_ids)
                RETURN node.id AS match_id, score ORDER BY score DESC LIMIT 1
            }
            RETURN row.idx AS idx, match_id
            """,
            rows=rows,
            threshold=threshold,
            exclude=exclude_document,
        )
        return {r["idx"]: r["match_id"] for r in out}

    # ------------------------------------------------------------------
    # Communities
    # ------------------------------------------------------------------

    async def entity_edges(self) -> list[tuple[str, str, float]]:
        rows = await self._run(
            "MATCH (a:Entity)-[r:RELATES]->(b:Entity) RETURN a.id AS a, b.id AS b, r.confidence AS w"
        )
        return [(r["a"], r["b"], float(r["w"] if r["w"] is not None else 1.0)) for r in rows]

    async def community_ids(self) -> set[str]:
        rows = await self._run("MATCH (c:Community) WHERE c.summary IS NOT NULL RETURN c.id AS id")
        return {r["id"] for r in rows}

    async def community_context(
        self, members: list[str], max_entities: int, max_relationships: int
    ) -> tuple[list[dict], list[dict]]:
        ents = await self._run(
            """
            MATCH (e:Entity) WHERE e.id IN $ids
            RETURN e.id AS id, e.name AS name, e.type AS type, e.description AS description,
                   COUNT { (e)-[:RELATES]-() } AS degree
            ORDER BY degree DESC LIMIT $limit
            """,
            ids=members,
            limit=max_entities,
        )
        rels = await self._run(
            """
            MATCH (a:Entity)-[r:RELATES]->(b:Entity) WHERE a.id IN $ids AND b.id IN $ids
            RETURN a.name AS src, b.name AS tgt, r.type AS type, r.description AS description
            ORDER BY r.confidence DESC LIMIT $limit
            """,
            ids=members,
            limit=max_relationships,
        )
        return ents, rels

    async def replace_communities(self, keep_ids: set[str], new: list, embeddings: np.ndarray) -> None:
        await self._run("MATCH (c:Community) WHERE NOT c.id IN $keep DETACH DELETE c", keep=list(keep_ids))
        rows = [
            {
                "id": c.id,
                "level": c.level,
                "parent": c.parent_id,
                "title": c.title,
                "summary": c.summary,
                "findings": c.findings,
                "members": c.members,
                "embedding": embeddings[i].tolist(),
            }
            for i, c in enumerate(new)
        ]
        # Parents first so PART_OF can attach.
        rows.sort(key=lambda r: -r["level"])
        for batch in _batches(rows):
            await self._run(
                """
                UNWIND $rows AS row
                MERGE (c:Community {id: row.id})
                SET c.level = row.level, c.title = row.title, c.summary = row.summary,
                    c.findings = row.findings, c.size = size(row.members)
                WITH c, row
                CALL db.create.setNodeVectorProperty(c, 'embedding', row.embedding)
                WITH c, row
                CALL (c, row) {
                    WITH c, row WHERE row.parent IS NOT NULL
                    MATCH (p:Community {id: row.parent})
                    MERGE (c)-[:PART_OF]->(p)
                }
                WITH c, row
                UNWIND row.members AS mid
                MATCH (e:Entity {id: mid})
                MERGE (e)-[:IN_COMMUNITY]->(c)
                """,
                rows=batch,
            )

    async def search_communities(self, vector: np.ndarray, k: int = 5) -> list[dict[str, Any]]:
        return await self._run(
            """
            CALL db.index.vector.queryNodes('community_embedding', $k, $vector) YIELD node, score
            OPTIONAL MATCH (e:Entity)-[:IN_COMMUNITY]->(node)
            WITH node, score, e ORDER BY COUNT { (e)-[:RELATES]-() } DESC
            WITH node, score, collect(e.name)[..8] AS top_entities, collect(e.id) AS member_ids
            RETURN node.id AS id, node.level AS level, node.title AS title, node.summary AS summary,
                   node.findings AS findings, node.size AS size, top_entities, member_ids, score
            ORDER BY score DESC
            """,
            vector=vector.tolist(),
            k=k,
        )

    async def list_communities(self) -> list[dict[str, Any]]:
        return await self._run(
            """
            MATCH (c:Community)
            OPTIONAL MATCH (c)-[:PART_OF]->(p:Community)
            RETURN c.id AS id, c.level AS level, c.title AS title, c.summary AS summary,
                   c.findings AS findings, c.size AS size, p.id AS parent_id,
                   [(e:Entity)-[:IN_COMMUNITY]->(c) | e.id] AS member_ids
            ORDER BY c.level DESC, c.size DESC
            """
        )

    # ------------------------------------------------------------------
    # Entity search (agent tool)
    # ------------------------------------------------------------------

    async def search_entities(self, text: str, vector: np.ndarray, k: int = 8) -> list[dict[str, Any]]:
        """Hybrid entity lookup: full-text on names/descriptions fused with vector similarity
        (reciprocal rank fusion)."""
        rows = await self._run(
            """
            CALL () {
                CALL db.index.fulltext.queryNodes('entity_names', $q, {limit: $k}) YIELD node, score
                WITH collect(node) AS ns
                UNWIND range(0, size(ns) - 1) AS rank
                RETURN ns[rank] AS node, 1.0 / (60 + rank) AS rrf
                UNION ALL
                CALL db.index.vector.queryNodes('entity_embedding', $k, $vector) YIELD node, score
                WITH collect(node) AS ns
                UNWIND range(0, size(ns) - 1) AS rank
                RETURN ns[rank] AS node, 1.0 / (60 + rank) AS rrf
            }
            WITH node, sum(rrf) AS fused
            RETURN node.id AS id, node.name AS name, node.type AS type,
                   node.description AS description, node.aliases AS aliases,
                   COUNT { (node)-[:RELATES]-() } AS degree, fused
            ORDER BY fused DESC LIMIT $k
            """,
            q=_lucene_escape(text),
            vector=vector.tolist(),
            k=k,
        )
        return rows

    async def chunks_by_ids(self, chunk_ids: list[str]) -> list[dict[str, Any]]:
        return await self._run(
            """
            MATCH (c:Chunk) WHERE c.id IN $ids
            RETURN c.id AS chunk_id, c.text AS text, c.page_number AS page_number,
                   c.document_id AS document_id, c.document_name AS document_name
            """,
            ids=chunk_ids,
        )

    # ------------------------------------------------------------------
    # Manual graph mutations
    # ------------------------------------------------------------------

    async def create_entity(self, entity: Entity) -> None:
        await self.write_graph([entity], [None], [])

    async def update_entity(
        self, entity_id: str, name: str | None, type_: str | None, description: str | None
    ) -> GraphNode | None:
        props: dict[str, Any] = {}
        if name is not None:
            props["name"] = name
        if type_ is not None:
            props["type"] = type_.upper()
        if description is not None:
            props["description"] = description
        rows = await self._run(
            "MATCH (e:Entity {id: $id}) SET e += $props RETURN e", id=entity_id, props=props
        )
        return self._to_node(rows[0]["e"]) if rows else None

    async def create_relationship(self, rel: Relationship) -> None:
        await self.write_graph([], [], [rel])

    async def get_orphaned_neighbors(self, entity_id: str) -> list[GraphNode]:
        rows = await self._run(
            """
            MATCH (n:Entity {id: $entity_id})-[:RELATES]-(neighbor:Entity)
            WITH DISTINCT neighbor,
                 COUNT { (neighbor)-[:RELATES]-(other:Entity) WHERE other.id <> $entity_id } AS others
            WHERE others = 0
            RETURN neighbor
            """,
            entity_id=entity_id,
        )
        return [self._to_node(r["neighbor"]) for r in rows]

    async def get_edge_orphan_target(self, edge_id: str) -> GraphNode | None:
        rows = await self._run(
            """
            MATCH (:Entity)-[r:RELATES {id: $edge_id}]->(tgt:Entity)
            WHERE COUNT { (tgt)-[:RELATES]-() } = 1
            RETURN tgt
            """,
            edge_id=edge_id,
        )
        return self._to_node(rows[0]["tgt"]) if rows else None

    async def delete_entity(self, entity_id: str, cascade: bool = False) -> None:
        if cascade:
            await self._run(
                """
                MATCH (n:Entity {id: $entity_id})-[:RELATES]-(neighbor:Entity)
                WITH DISTINCT neighbor
                WHERE COUNT { (neighbor)-[:RELATES]-(other:Entity) WHERE other.id <> $entity_id } = 0
                DETACH DELETE neighbor
                """,
                entity_id=entity_id,
            )
        await self._run("MATCH (e:Entity {id: $id}) DETACH DELETE e", id=entity_id)

    async def delete_edge(self, edge_id: str, delete_orphan_target: bool = False) -> None:
        if delete_orphan_target:
            await self._run(
                """
                MATCH (:Entity)-[r:RELATES {id: $edge_id}]->(tgt:Entity)
                WITH r, tgt, COUNT { (tgt)-[:RELATES]-() } AS total
                DELETE r
                WITH tgt, total WHERE total = 1
                DETACH DELETE tgt
                """,
                edge_id=edge_id,
            )
        else:
            await self._run("MATCH ()-[r:RELATES {id: $id}]-() DELETE r", id=edge_id)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _run(self, cypher: str, **params: Any) -> list[dict[str, Any]]:
        assert self._driver is not None, "GraphStore.connect() was not called"
        records, _, _ = await self._driver.execute_query(cypher, params, database_=self._db)
        return [dict(r) for r in records]

    @staticmethod
    def _to_status(node: Node) -> DocumentStatus:
        props = dict(node)
        props["document_id"] = props.pop("id")
        return DocumentStatus.model_validate(props)

    @staticmethod
    def _to_node(node: Node) -> GraphNode:
        props = dict(node)
        return GraphNode(
            id=props["id"],
            name=props.get("name", ""),
            type=props.get("type", "OTHER"),
            description=props.get("description") or None,
            source_document=props.get("source_document", ""),
            chunk_count=len(props.get("source_chunk_ids") or []),
        )

    @staticmethod
    def _to_edge(rel: Neo4jRel, src_id: str, tgt_id: str) -> GraphEdge:
        props = dict(rel)
        return GraphEdge(
            id=props["id"],
            source=src_id,
            target=tgt_id,
            type=props.get("type", "RELATES"),
            description=props.get("description") or None,
            confidence=float(props.get("confidence", 1.0)),
            source_document=props.get("source_document", ""),
        )


def _batches(rows: list[dict], size: int = _WRITE_BATCH):
    for i in range(0, len(rows), size):
        yield rows[i : i + size]


_LUCENE_SPECIAL = set('+-&|!(){}[]^"~*?:\\/')


def _lucene_escape(text: str) -> str:
    return "".join(f"\\{ch}" if ch in _LUCENE_SPECIAL else ch for ch in text) or "*"


def _jsonable(value: Any) -> Any:
    """Convert Neo4j graph types into JSON-friendly structures."""
    if isinstance(value, Node):
        return {
            "_labels": sorted(value.labels),
            **{k: _jsonable(v) for k, v in value.items() if k not in _HIDDEN_PROPS},
        }
    if isinstance(value, Neo4jRel):
        return {"_type": value.type, **{k: _jsonable(v) for k, v in value.items()}}
    if isinstance(value, Path):
        return {
            "nodes": [_jsonable(n) for n in value.nodes],
            "relationships": [_jsonable(r) for r in value.relationships],
        }
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
