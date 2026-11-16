from app.models import Entity, Relationship
from app.services.embeddings import HashEmbedder
from app.services.resolver import EntityResolver


def ent(name, type_="PERSON", chunk="c1"):
    return Entity(name=name, type=type_, source_document="d.pdf", document_id="d", source_chunk_ids=[chunk])


def rel(a, b, t="KNOWS"):
    return Relationship(
        source_entity_id=a.id, target_entity_id=b.id, type=t, source_chunk_id="c1", source_document="d.pdf"
    )


def test_exact_and_fuzzy_merge_across_batches():
    r = EntityResolver(embedder=HashEmbedder(), threshold=0.75)
    a1, b1 = ent("Ada Lovelace", chunk="c1"), ent("Charles Babbage", chunk="c1")
    r.resolve([a1, b1], [rel(a1, b1)])
    a2 = ent("ada  lovelace", chunk="c2")  # exact after normalisation
    a3 = ent("Ada Lovelace.", chunk="c3")  # near-duplicate
    r.resolve([a2, a3], [])
    names = sorted(e.name for e in r.all_entities)
    assert names == ["Ada Lovelace", "Charles Babbage"]
    ada = next(e for e in r.all_entities if e.name == "Ada Lovelace")
    assert ada.source_chunk_ids == ["c1", "c2", "c3"]
    assert "Ada Lovelace." in ada.aliases


def test_types_are_never_merged():
    r = EntityResolver(embedder=HashEmbedder(), threshold=0.5)
    r.resolve([ent("Mercury", "LOCATION"), ent("Mercury", "CONCEPT")], [])
    assert len(r.all_entities) == 2


def test_relationships_rewritten_and_deduplicated():
    r = EntityResolver(embedder=HashEmbedder(), threshold=0.9)
    a1, b1 = ent("Ada"), ent("Charles")
    first = r.resolve([a1, b1], [rel(a1, b1)])
    a2, b2 = ent("Ada", chunk="c2"), ent("Charles", chunk="c2")
    second = r.resolve([a2, b2], [rel(a2, b2), rel(a2, a2)])
    assert len(first) == 1
    assert second == []  # duplicate of first, and the self-loop is dropped
    assert first[0].source_entity_id == a1.id


def test_embedding_lookup():
    r = EntityResolver(embedder=HashEmbedder())
    a = ent("Ada")
    r.resolve([a], [])
    assert r.embedding_for(a).shape == (384,)
