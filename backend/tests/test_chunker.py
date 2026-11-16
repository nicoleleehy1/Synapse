from app.services.chunker import Chunker


def _pages(n_sentences: int, per_page: int = 20) -> list[dict]:
    sents = [f"Sentence number {i} talks about topic {i % 7} in some detail." for i in range(n_sentences)]
    return [
        {"page_number": p + 1, "text": " ".join(sents[p * per_page : (p + 1) * per_page])}
        for p in range((n_sentences + per_page - 1) // per_page)
    ]


def test_chunks_respect_max_tokens_and_overlap():
    c = Chunker(min_tokens=50, max_tokens=120, overlap_tokens=30)
    chunks = c.chunk_pages(_pages(200), "doc-1", "doc.pdf")
    assert len(chunks) > 5
    assert all(ch.token_count <= 120 for ch in chunks)
    # Consecutive chunks overlap (the sliding window steps back).
    for a, b in zip(chunks, chunks[1:], strict=False):
        assert a.text.split(". ")[-1] in b.text or b.text[:40] in a.text


def test_chunks_carry_provenance():
    chunks = Chunker(max_tokens=100).chunk_pages(_pages(60), "doc-1", "doc.pdf")
    assert {ch.document_id for ch in chunks} == {"doc-1"}
    assert chunks[0].page_number == 1
    assert chunks[-1].page_number == 3
    assert len({ch.id for ch in chunks}) == len(chunks)


def test_empty_input():
    assert Chunker().chunk_pages([], "d", "d.pdf") == []


def test_token_estimate_is_reasonable():
    c = Chunker()
    assert 8 <= c._count("The quick brown fox jumps over the lazy dog.") <= 12
