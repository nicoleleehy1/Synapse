"""Hierarchical community detection and summarisation (the "global" half of GraphRAG).

1. Pull the entity graph out of Neo4j (edge weight = relationship confidence).
2. Leiden (modularity) partitions it into top-level topics; each topic that is
   large enough is partitioned again into sub-topics, giving a two-level
   hierarchy: (:Community {level: 0})-[:PART_OF]->(:Community {level: 1}).
3. Claude writes a title, summary and key findings for every community from
   its entities and relationships (structured outputs, concurrently).
4. Summaries are embedded and stored in a vector index, so "big picture"
   questions can be answered from community reports instead of a handful of
   nearest passages.

Community ids are a hash of their member set, so re-running after a new upload
only re-summarises communities whose membership actually changed.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass, field

import anthropic
import networkx as nx
from pydantic import BaseModel, Field

from app.config import settings
from app.services.embeddings import Embedder, embed_async, get_embedder
from app.services.graph_store import GraphStore

logger = logging.getLogger(__name__)

MIN_COMMUNITY_SIZE = 3
MAX_ENTITIES_IN_PROMPT = 60
MAX_RELATIONSHIPS_IN_PROMPT = 120


@dataclass
class Community:
    id: str
    level: int
    members: list[str]
    parent_id: str | None = None
    title: str = ""
    summary: str = ""
    findings: list[str] = field(default_factory=list)


class _Report(BaseModel):
    title: str = Field(description="A specific 3-8 word title naming what ties this cluster together.")
    summary: str = Field(description="2-4 sentences: what this cluster is about and why it matters.")
    findings: list[str] = Field(description="3-5 concrete, self-contained findings grounded in the data.")


REPORT_SYSTEM = """You write concise reports about clusters of a knowledge graph extracted from
documents. You receive the entities in one cluster and the relationships among them.
Describe what ties the cluster together using only the information given. Be specific:
name the key entities and how they relate. Do not speculate beyond the data."""


def community_id(level: int, members: list[str]) -> str:
    digest = hashlib.blake2b("|".join(sorted(members)).encode(), digest_size=8).hexdigest()
    return f"c{level}-{digest}"


def detect_communities(
    graph: nx.Graph, seed: int = 42, fine_resolution: float = 1.0, coarse_resolution: float = 0.3
) -> list[Community]:
    """Bottom-up two-level hierarchy. Pure function: easy to test, no I/O.

    1. Leiden (modularity) on the entity graph gives fine-grained sub-topics.
    2. Each sub-topic is collapsed into a super-node (intra-community weight kept
       as a self-loop, inter-community weights summed) and Leiden runs again on
       that quotient graph, grouping sub-topics into broad topics.
    """
    if graph.number_of_edges() == 0:
        return []
    fine = [
        sorted(m)
        for m in nx.community.leiden_communities(
            graph, weight="weight", resolution=fine_resolution, seed=seed, metric="modularity"
        )
    ]
    owner = {node: i for i, members in enumerate(fine) for node in members}
    q = nx.Graph()
    q.add_nodes_from(range(len(fine)))
    for u, v, data in graph.edges(data=True):
        a, b = owner[u], owner[v]
        w = q.get_edge_data(a, b, {}).get("weight", 0.0) + data.get("weight", 1.0)
        q.add_edge(a, b, weight=w)
    coarse = nx.community.leiden_communities(
        q, weight="weight", resolution=coarse_resolution, seed=seed, metric="modularity"
    )

    out: list[Community] = []
    for group in sorted(coarse, key=lambda g: min(g)):
        children = [fine[i] for i in sorted(group)]
        members = sorted(n for c in children for n in c)
        if len(members) < MIN_COMMUNITY_SIZE:
            continue
        top = Community(id=community_id(1, members), level=1, members=members)
        out.append(top)
        if len(children) < 2:
            continue  # a broad topic with no meaningful sub-structure
        for child in children:
            if len(child) >= MIN_COMMUNITY_SIZE:
                out.append(
                    Community(id=community_id(0, child), level=0, members=child, parent_id=top.id)
                )
    return out


class CommunityBuilder:
    def __init__(
        self,
        graph_store: GraphStore,
        client: anthropic.AsyncAnthropic | None = None,
        embedder: Embedder | None = None,
    ) -> None:
        self._gs = graph_store
        self._llm = client or anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key or None)
        self._embedder = embedder
        self._lock = asyncio.Lock()  # one rebuild at a time

    async def rebuild(self) -> int:
        """Recompute communities; returns how many were (re)summarised."""
        async with self._lock:
            edges = await self._gs.entity_edges()
            g = nx.Graph()
            for src, tgt, w in edges:
                prev = g.get_edge_data(src, tgt, {}).get("weight", 0.0)
                g.add_edge(src, tgt, weight=prev + max(w, 0.05))
            communities = await asyncio.to_thread(detect_communities, g)

            existing = await self._gs.community_ids()
            fresh = [c for c in communities if c.id not in existing]
            sem = asyncio.Semaphore(settings.extraction_concurrency)

            async def summarise(c: Community) -> None:
                async with sem:
                    try:
                        await self._summarise(c)
                    except Exception:  # noqa: BLE001 - keep the community with a fallback title
                        logger.exception("Summarising community %s failed", c.id)

            await asyncio.gather(*(summarise(c) for c in fresh))
            fresh = [c for c in fresh if c.summary]
            vecs = await embed_async(
                [f"{c.title}. {c.summary}" for c in fresh], self._embedder or get_embedder()
            )
            await self._gs.replace_communities(
                keep_ids={c.id for c in communities}, new=fresh, embeddings=vecs
            )
            logger.info("Communities: %d total, %d newly summarised", len(communities), len(fresh))
            return len(fresh)

    async def _summarise(self, c: Community) -> None:
        ents, rels = await self._gs.community_context(
            c.members, MAX_ENTITIES_IN_PROMPT, MAX_RELATIONSHIPS_IN_PROMPT
        )
        lines = ["<entities>"]
        lines += [f"- {e['name']} ({e['type']}): {e['description'] or ''}" for e in ents]
        lines += ["</entities>", "<relationships>"]
        lines += [
            f"- {r['src']} -[{r['type']}]-> {r['tgt']}"
            + (f": {r['description']}" if r["description"] else "")
            for r in rels
        ]
        lines.append("</relationships>")
        kwargs: dict = dict(
            model=settings.llm_model,
            max_tokens=4000,
            system=REPORT_SYSTEM,
            messages=[{"role": "user", "content": "\n".join(lines)}],
            output_format=_Report,
            output_config={"effort": settings.extraction_effort},
        )
        if settings.llm_fallbacks:
            resp = await self._llm.beta.messages.parse(
                betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs
            )
        else:
            resp = await self._llm.messages.parse(**kwargs)
        if resp.stop_reason in ("refusal", "max_tokens") or resp.parsed_output is None:
            return
        report: _Report = resp.parsed_output
        c.title, c.summary, c.findings = report.title.strip(), report.summary.strip(), report.findings


class CommunityScheduler:
    """Debounced background rebuilds: many uploads in a row cause one rebuild, not many."""

    def __init__(self, builder: CommunityBuilder) -> None:
        self._builder = builder
        self._task: asyncio.Task | None = None
        self._dirty = False

    def request(self) -> None:
        self._dirty = True
        if self._task is None or self._task.done():
            self._task = asyncio.get_running_loop().create_task(self._loop())

    async def _loop(self) -> None:
        while self._dirty:
            self._dirty = False
            try:
                await self._builder.rebuild()
            except Exception:  # noqa: BLE001
                logger.exception("Community rebuild failed")

    async def wait(self) -> None:
        """Wait for any in-flight rebuild (used by tests and the eval harness)."""
        while self._task is not None and not self._task.done():
            await asyncio.shield(self._task)
