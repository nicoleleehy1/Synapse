"""End-to-end tests against a real Neo4j (set NEO4J_TEST_URI, e.g. bolt://localhost:7687)."""

from __future__ import annotations

import asyncio
import json
import os

import httpx
import pytest
import pytest_asyncio

from app.models import Entity, Relationship, TextChunk
from app.services.embeddings import HashEmbedder
from app.services.extractor import Extractor, _ExtractionPayload
from app.services.graph_store import GraphStore, ReadOnlyViolation
from app.services.pipeline import Pipeline
from app.services.retriever import Retriever
from tests.fakes import FakeAnthropic

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
    await store._run("MATCH (n) WHERE n:Entity OR n:Chunk OR n:Document DETACH DELETE n")
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
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


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
    assert ans["answer"].startswith("Neurons connect")
    assert ans["sources"] and ans["graph_context"]["nodes"]

    assert (
        await client.post("/graph/cypher", json={"cypher": "MATCH (n) DETACH DELETE n"})
    ).status_code == 403
    assert (await client.post("/graph/cypher", json={"cypher": "MATCH (n RETURN n"})).status_code == 400

    assert (await client.delete(f"/documents/{doc_id}")).status_code == 200
    assert (await client.get(f"/documents/{doc_id}/status")).status_code == 404


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
