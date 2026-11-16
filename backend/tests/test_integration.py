"""End-to-end tests against a real Neo4j (set NEO4J_TEST_URI, e.g. bolt://localhost:7687)."""

from __future__ import annotations

import asyncio
import json
import os

import httpx
import pytest
import pytest_asyncio

from app.models import Entity, Relationship, TextChunk
from app.services.agent import GraphRAGAgent
from app.services.communities import CommunityBuilder, CommunityScheduler
from app.services.embeddings import HashEmbedder
from app.services.extractor import Extractor, _ExtractionPayload
from app.services.graph_store import GraphStore, ReadOnlyViolation
from app.services.pipeline import Pipeline
from app.services.retriever import Retriever
from app.services.study import StudyService, _CardBatch
from tests.fakes import FakeAnthropic, ScriptedAnthropic, text_block, tool_block

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not os.environ.get("NEO4J_TEST_URI"), reason="NEO4J_TEST_URI not set"),
]

EMB = HashEmbedder()


@pytest_asyncio.fixture(scope="session")
async def store():
    gs = GraphStore()
    await gs.connect()
    yield gs
    await gs.close()


@pytest_asyncio.fixture(autouse=True)
async def clean(store):
    await store._run(
        "MATCH (n) WHERE n:Entity OR n:Chunk OR n:Document OR n:Community OR n:Card OR n:Review DETACH DELETE n"
    )
    yield


def _chunk(i: int, text: str, doc="d1") -> TextChunk:
    return TextChunk(
        id=f"{doc}-c{i}",
        text=text,
        page_number=i + 1,
        document_id=doc,
        document_name=f"{doc}.pdf",
        char_start=0,
        char_end=len(text),
        token_count=10,
    )


async def _seed_document(store: GraphStore, doc: str = "d1") -> None:
    from app.models import DocumentStatus

    await store.save_document(DocumentStatus(document_id=doc, filename=f"{doc}.pdf", status="complete"))


async def test_vector_search_and_document_filter(store):
    await _seed_document(store, "d1")
    await _seed_document(store, "d2")
    c1 = [
        _chunk(0, "Photosynthesis converts light into chemical energy."),
        _chunk(1, "The French Revolution began in 1789."),
    ]
    c2 = [_chunk(0, "Photosynthesis happens in chloroplasts.", doc="d2")]
    await store.write_chunks(c1, EMB.embed([c.text for c in c1]))
    await store.write_chunks(c2, EMB.embed([c.text for c in c2]))
    await asyncio.sleep(1.5)  # vector index is eventually consistent

    q = EMB.embed(["photosynthesis light energy"])[0]
    hits = await store.search_chunks(q, k=3)
    assert hits[0]["text"].startswith("Photosynthesis")
    only_d2 = await store.search_chunks(q, k=3, document_id="d2")
    assert {h["document_id"] for h in only_d2} == {"d2"}


async def test_graph_write_and_multi_hop_neighbourhood(store):
    await _seed_document(store)
    chunk = _chunk(0, "A knows B, B knows C, C knows D.")
    await store.write_chunks([chunk], EMB.embed([chunk.text]))
    ents = [
        Entity(name=n, type="PERSON", source_document="d1.pdf", document_id="d1", source_chunk_ids=[chunk.id])
        for n in "ABCD"
    ]
    rels = [
        Relationship(
            source_entity_id=ents[i].id,
            target_entity_id=ents[i + 1].id,
            type="KNOWS",
            source_chunk_id=chunk.id,
            source_document="d1.pdf",
        )
        for i in range(3)
    ]
    await store.write_graph(ents, list(EMB.embed([e.name for e in ents])), rels)

    full = await store.get_full_graph(document_id="d1")
    assert len(full.nodes) == 4 and len(full.edges) == 3

    one = await store.get_entity_neighbourhood(ents[0].id, hop_depth=1)
    assert {n.name for n in one.nodes} == {"A", "B"} and len(one.edges) == 1
    two = await store.get_entity_neighbourhood(ents[0].id, hop_depth=2)
    assert {n.name for n in two.nodes} == {"A", "B", "C"} and len(two.edges) == 2

    isolated = Entity(name="Z", type="PERSON", source_document="Manual")
    await store.create_entity(isolated)
    alone = await store.get_entity_neighbourhood(isolated.id, hop_depth=2)
    assert [n.name for n in alone.nodes] == ["Z"] and alone.edges == []

    assert await store.get_entities_for_chunks([chunk.id]) != []
    orphans = await store.get_orphaned_neighbors(ents[0].id)
    assert [o.name for o in orphans] == []  # B still connects to C
    tail = await store.get_orphaned_neighbors(ents[3].id)
    assert tail == []  # C still connects to B

    await store.delete_document("d1")
    assert (await store.get_full_graph(document_id="d1")).nodes == []


@pytest.mark.parametrize(
    "cypher",
    [
        "CREATE (n:Hacked) RETURN n",
        "MATCH (n) DETACH DELETE n",
        "MATCH (d:Document) SET d.status = 'pwned'",
        "MERGE (x:Entity {id: 'evil'}) RETURN x",
        "CREATE INDEX evil IF NOT EXISTS FOR (n:X) ON (n.y)",
    ],
)
async def test_cypher_sandbox_rejects_writes(store, cypher):
    await _seed_document(store)
    with pytest.raises(ReadOnlyViolation):
        await store.execute_read_only(cypher)
    assert (await store.get_document("d1")).status == "complete"


async def test_cypher_sandbox_allows_reads_and_caps_rows(store, monkeypatch):
    from app.config import settings

    await _seed_document(store)
    rows = await store.execute_read_only("MATCH (d:Document) RETURN d, d.id AS id")
    assert rows[0]["id"] == "d1" and "_labels" in rows[0]["d"]
    monkeypatch.setattr(settings, "cypher_max_rows", 5)
    rows = await store.execute_read_only("UNWIND range(1, 100) AS x RETURN x")
    assert len(rows) == 5


# ── Full API flow ─────────────────────────────────────────────────────────────


def _fake_extraction(kwargs):
    text = kwargs["messages"][0]["content"]
    ents = [
        {"name": w, "type": "CONCEPT", "description": f"{w} concept."}
        for w in ("Neurons", "Synapses", "Neurotransmitters")
        if w.lower() in text.lower()
    ]
    rels = []
    if len(ents) >= 2:
        rels.append(
            {
                "source": ents[0]["name"],
                "target": ents[1]["name"],
                "type": "CONNECTED_BY",
                "description": "linked",
                "confidence": 0.9,
            }
        )
    return _ExtractionPayload.model_validate({"entities": ents, "relationships": rels})


@pytest_asyncio.fixture
async def client(store):
    from app.main import create_app

    app = create_app()
    fake = FakeAnthropic(parse_fn=_fake_extraction, text="Neurons connect via synapses [1].")
    app.state.graph_store = store
    app.state.pipeline = Pipeline(graph_store=store, extractor=Extractor(client=fake), embedder=EMB)
    app.state.retriever = Retriever(graph_store=store, client=fake, embedder=EMB)
    app.state.agent = GraphRAGAgent(
        graph_store=store,
        embedder=EMB,
        client=ScriptedAnthropic(
            [
                [tool_block("t1", "search_passages", {"query": "how neurons connect", "top_k": 3})],
                [text_block("Neurons connect via synapses [1].")],
            ]
        ),
    )
    app.state.study = StudyService(graph_store=store, client=FakeAnthropic(parse_fn=_fake_cards))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _fake_cards(kwargs):
    n = kwargs["messages"][0]["content"].count("<fact ")
    cards = [{"fact": i, "front": f"Question {i}?", "back": f"Answer {i}."} for i in range(1, n + 1)]
    cards.append({"fact": 99, "front": "out of range", "back": "dropped"})
    return _CardBatch.model_validate({"cards": cards})


async def test_upload_stream_query_delete(client, pdf_factory):
    pdf = pdf_factory(
        [
            "Neurons are cells that transmit signals. Synapses are junctions between neurons. " * 10,
            "Neurotransmitters cross synapses to carry the signal onward. " * 10,
        ]
    )
    with open(pdf, "rb") as fh:
        r = await client.post("/documents/upload", files={"file": ("brain.pdf", fh, "application/pdf")})
    assert r.status_code == 200, r.text
    doc_id = r.json()["document_id"]

    stages = []
    async with asyncio.timeout(30), client.stream("GET", f"/documents/{doc_id}/events") as resp:
        async for line in resp.aiter_lines():
            if line.startswith("data:"):
                data = json.loads(line[5:])
                if "status" in data:
                    stages.append(data["stage"])
                    if data["status"] in ("complete", "error"):
                        assert data["status"] == "complete", data
                        break
    assert stages[-1] == "done"
    assert "extracting" in stages

    status = (await client.get(f"/documents/{doc_id}/status")).json()
    assert status["entity_count"] == 3 and status["relationship_count"] >= 1
    assert [d["document_id"] for d in (await client.get("/documents/")).json()] == [doc_id]

    graph = (await client.get("/graph/", params={"document_id": doc_id})).json()
    assert {n["name"] for n in graph["nodes"]} == {"Neurons", "Synapses", "Neurotransmitters"}

    await asyncio.sleep(1.5)
    ans = (await client.post("/query/", json={"query": "How do neurons connect?"})).json()
    assert ans["answer"] == "Neurons connect via synapses [1]."
    assert ans["sources"] and ans["graph_context"]["nodes"] and ans["steps"] == 1

    assert (
        await client.post("/graph/cypher", json={"cypher": "MATCH (n) DETACH DELETE n"})
    ).status_code == 403
    assert (await client.post("/graph/cypher", json={"cypher": "MATCH (n RETURN n"})).status_code == 400

    # Source viewer: the PDF is kept and each passage knows where it sits on the page.
    pdf_resp = await client.get(f"/documents/{doc_id}/pdf")
    assert pdf_resp.status_code == 200 and pdf_resp.content.startswith(b"%PDF-")
    chunk = (await client.get(f"/documents/chunks/{ans['sources'][0]['chunk_id']}")).json()
    assert chunk["has_pdf"] and chunk["highlights"]
    assert all(0 <= h["x0"] < h["x1"] <= 1 for h in chunk["highlights"])
    assert (await client.get("/documents/chunks/nope")).status_code == 404

    # Flashcards from the graph's relationships, then one review.
    created = (await client.post("/study/generate", json={"document_id": doc_id, "count": 5})).json()
    assert created["created"] == status["relationship_count"]
    due = (await client.get("/study/due")).json()
    assert len(due) == created["created"] and due[0]["state"] == "new"
    assert due[0]["intervals"]["1"] < due[0]["intervals"]["3"] < due[0]["intervals"]["4"]
    reviewed = (await client.post(f"/study/cards/{due[0]['id']}/review", json={"rating": 3})).json()
    assert reviewed["state"] == "review" and reviewed["reps"] == 1
    assert (await client.post("/study/cards/nope/review", json={"rating": 3})).status_code == 404
    assert (await client.post(f"/study/cards/{due[0]['id']}/review", json={"rating": 5})).status_code == 422
    mastery = {m["entity_id"]: m for m in (await client.get("/study/mastery")).json()}
    assert set(due[0]["entity_ids"]) <= set(mastery)
    assert max(m["mastery"] for m in mastery.values()) == pytest.approx(1.0, abs=0.01)
    stats = (await client.get("/study/stats", params={"tz_offset_minutes": -480})).json()
    assert stats["reviewed_today"] == 1 and stats["streak_days"] == 1 and stats["activity"][-1] == 1
    assert stats["retention_30d"] == 1.0

    from app.services.pipeline import stored_pdf_path

    assert stored_pdf_path(doc_id).exists()
    assert (await client.delete(f"/documents/{doc_id}")).status_code == 200
    assert (await client.get(f"/documents/{doc_id}/status")).status_code == 404
    assert not stored_pdf_path(doc_id).exists()
    assert (await client.get("/study/due")).json() == []  # cards go with their document


async def test_upload_validation(client, tmp_path):
    fake = tmp_path / "x.pdf"
    fake.write_bytes(b"not a pdf at all")
    with open(fake, "rb") as fh:
        r = await client.post("/documents/upload", files={"file": ("x.pdf", fh, "application/pdf")})
    assert r.status_code == 400
    r = await client.post("/documents/upload", files={"file": ("x.txt", b"%PDF-", "text/plain")})
    assert r.status_code == 400


async def test_health(client):
    r = await client.get("/health")
    assert r.json() == {"status": "ok", "neo4j": True}


# ── Cross-document resolution ─────────────────────────────────────────────────


async def test_entities_merge_across_documents(store):
    from app.models import DocumentStatus

    fake = FakeAnthropic(parse_fn=_fake_extraction)
    pipe = Pipeline(graph_store=store, extractor=Extractor(client=fake), embedder=EMB)
    ids = []
    for name, text in [
        ("one.pdf", "Neurons and Synapses work together. " * 30),
        ("two.pdf", "Synapses release Neurotransmitters. " * 30),
    ]:
        st = DocumentStatus(document_id=name.split(".")[0], filename=name, status="queued")
        await store.save_document(st)
        ids.append(st.document_id)
        import pathlib
        import tempfile

        from tests.conftest import make_pdf

        p = pathlib.Path(tempfile.mkdtemp()) / name
        make_pdf(p, [text])
        assert (await pipe.process(p, st)).status == "complete"
        await asyncio.sleep(1.2)  # let the entity vector index catch up before the next doc

    rows = await store._run("MATCH (e:Entity {name: 'Synapses'}) RETURN e.document_ids AS docs")
    assert len(rows) == 1, "Synapses should be one node shared by both documents"
    assert sorted(rows[0]["docs"]) == ["one", "two"]
    both = await store.get_full_graph()
    assert {n.name for n in both.nodes} == {"Neurons", "Synapses", "Neurotransmitters"}

    await store.delete_document("one")
    left = await store.get_full_graph()
    assert {n.name for n in left.nodes} == {"Synapses", "Neurotransmitters"}
    assert len(left.edges) == 1  # the one.pdf relationship went with its document
    await store.delete_document("two")
    assert (await store.get_full_graph()).nodes == []


# ── Communities ───────────────────────────────────────────────────────────────


async def _seed_clusters(store):
    await _seed_document(store)
    groups = [["Ada", "Babbage", "Engine", "Punch Cards"], ["Curie", "Radium", "Polonium", "Sorbonne"]]
    ents, rels = [], []
    for g in groups:
        es = [Entity(name=n, type="CONCEPT", source_document="d1.pdf", document_id="d1") for n in g]
        ents += es
        for i in range(len(es)):
            for j in range(i + 1, len(es)):
                rels.append(
                    Relationship(
                        source_entity_id=es[i].id,
                        target_entity_id=es[j].id,
                        type="RELATED_TO",
                        source_chunk_id="",
                        source_document="d1.pdf",
                        document_id="d1",
                    )
                )
    rels.append(
        Relationship(
            source_entity_id=ents[0].id,
            target_entity_id=ents[4].id,
            type="INSPIRED",
            confidence=0.1,
            source_chunk_id="",
            source_document="d1.pdf",
            document_id="d1",
        )
    )
    await store.write_graph(ents, list(EMB.embed([e.name for e in ents])), rels)
    return ents


def _fake_report(kwargs):
    from app.services.communities import _Report

    text = kwargs["messages"][0]["content"]
    title = "Computing pioneers" if "Babbage" in text else "Radioactivity research"
    return _Report(title=title, summary=f"About {title.lower()}.", findings=["finding one", "finding two"])


async def test_community_build_search_and_incremental_reuse(store):
    await _seed_clusters(store)
    fake = FakeAnthropic(parse_fn=_fake_report)
    builder = CommunityBuilder(graph_store=store, client=fake, embedder=EMB)
    assert await builder.rebuild() == 2
    calls = len(fake.messages.calls)

    topics = await store.list_communities()
    assert {t["title"] for t in topics} == {"Computing pioneers", "Radioactivity research"}
    assert all(len(t["member_ids"]) == 4 for t in topics)

    await asyncio.sleep(1.2)
    hits = await store.search_communities(EMB.embed(["computing pioneers"])[0], k=1)
    assert hits[0]["title"] == "Computing pioneers"
    assert "Babbage" in hits[0]["top_entities"]

    # Nothing changed: no new LLM calls.
    assert await builder.rebuild() == 0
    assert len(fake.messages.calls) == calls

    sched = CommunityScheduler(builder)
    sched.request()
    sched.request()
    await sched.wait()
    assert len(fake.messages.calls) == calls


# ── Agent ─────────────────────────────────────────────────────────────────────


async def test_agent_plans_retrieval_cites_and_self_corrects(store):
    ents = await _seed_clusters(store)
    chunk = _chunk(0, "Ada Lovelace wrote the first program for Babbage's Analytical Engine.")
    await store.write_chunks([chunk], EMB.embed([chunk.text]))
    await store._run(
        "MATCH (e:Entity {name: 'Ada'}), (c:Chunk {id: $cid}) MERGE (e)-[:MENTIONED_IN]->(c)", cid=chunk.id
    )
    await asyncio.sleep(1.2)

    def explore_turn(kwargs):
        # React to the previous tool result like a real model: pick the id it was given.
        last = kwargs["messages"][-1]["content"]
        listing = next(r["content"] for r in last if r["tool_use_id"] == "t2")
        ada_id = listing.split("id=")[1].split(" ")[0]
        return [
            tool_block("t3", "explore_entities", {"entity_ids": [ada_id], "depth": 1}),
            tool_block("t4", "run_cypher", {"cypher": "MATCH (n) DETACH DELETE n", "purpose": "oops"}),
        ]

    client = ScriptedAnthropic(
        [
            [
                tool_block("t1", "search_passages", {"query": "first program", "top_k": 3}),
                tool_block("t2", "search_entities", {"query": "Ada"}),
            ],
            explore_turn,
            [
                tool_block(
                    "t5",
                    "run_cypher",
                    {
                        "cypher": "MATCH (e:Entity)-[:RELATES]-(o) RETURN e.name AS name, count(o) AS n ORDER BY n DESC LIMIT 3",
                        "purpose": "most connected entities",
                    },
                )
            ],
            [text_block("Ada Lovelace wrote the first program [1].")],
        ]
    )
    agent = GraphRAGAgent(graph_store=store, client=client, embedder=EMB)
    events = [e async for e in agent.run("Who wrote the first program?")]
    kinds = [e["type"] for e in events]

    assert kinds.count("step") == 5 and kinds.count("step_result") == 5
    results = {e["id"]: e for e in events if e["type"] == "step_result"}
    assert results["t4"]["is_error"] and "read-only" in results["t4"]["summary"]
    assert not results["t5"]["is_error"] and "3 rows" in results["t5"]["summary"]
    assert (await store.get_full_graph()).nodes, "the write attempt must not have deleted anything"

    done = events[-1]
    assert done["type"] == "done"
    assert done["answer"] == "Ada Lovelace wrote the first program [1]."
    assert done["sources"][0]["chunk_id"] == chunk.id
    assert ents[0].id in done["highlight_ids"]
    assert {n["name"] for n in done["graph"]["nodes"]} >= {"Ada", "Babbage"}
    assert done["usage"]["input_tokens"] == 400

    # The errored tool result went back to the model flagged as an error.
    turn3_msgs = client.messages.stream_calls[2]["messages"]
    t4 = next(r for r in turn3_msgs[-1]["content"] if r["tool_use_id"] == "t4")
    assert t4["is_error"] is True
    # Tools were offered on every turn, with prompt caching and refusal fallbacks.
    assert all(c["tool_choice"] == {"type": "auto"} for c in client.messages.stream_calls)
    assert client.messages.stream_calls[0]["fallbacks"] == "default"


async def test_agent_step_budget_forces_an_answer(store):
    await _seed_document(store)
    loop_turn = [tool_block("x", "search_entities", {"query": "anything"})]
    client = ScriptedAnthropic([loop_turn] * 3 + [[text_block("Best effort answer.")]])
    agent = GraphRAGAgent(graph_store=store, client=client, embedder=EMB, max_steps=3)
    done = await agent.answer("loop forever")
    assert done["answer"] == "Best effort answer."
    assert client.messages.stream_calls[-1]["tool_choice"] == {"type": "none"}
