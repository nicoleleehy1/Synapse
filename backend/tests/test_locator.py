from app.services.chunker import Chunker
from app.services.locator import SourceLocator
from app.services.pdf_processor import PDFProcessor

PAGE1 = (
    "Photosynthesis converts light into chemical energy. It takes place in the chloroplasts of "
    "plant cells. The light reactions produce ATP and NADPH. "
) * 3
PAGE2 = "The Calvin cycle fixes carbon dioxide into sugar. Rubisco is the enzyme responsible. " * 3


def test_locates_a_sentence_on_the_right_page(pdf_factory):
    pdf = pdf_factory([PAGE1, PAGE2])
    loc = SourceLocator(pdf)
    rects = loc.locate("The Calvin cycle fixes carbon dioxide into sugar.", page_number=1)
    assert rects and {r["page"] for r in rects} == {2}
    for r in rects:
        assert 0 <= r["x0"] < r["x1"] <= 1 and 0 <= r["y0"] < r["y1"] <= 1
    assert loc.locate("words that are nowhere in the document", 1) == []
    assert loc.locate("anything", 99) == []


def test_every_pipeline_chunk_is_located(pdf_factory):
    """Chunks come from cleaned text; the locator must still find each of them."""
    pdf = pdf_factory([PAGE1, PAGE2])
    pages = PDFProcessor().extract(pdf)
    chunks = Chunker(min_tokens=30, max_tokens=50, overlap_tokens=10).chunk_pages(pages, "d", "d.pdf")
    loc = SourceLocator(pdf)
    assert len(chunks) > 2
    for c in chunks:
        rects = loc.locate(c.text, c.page_number)
        assert rects, c.text
        assert min(r["page"] for r in rects) == c.page_number


def test_multi_line_span_gives_one_rect_per_line(pdf_factory):
    pdf = pdf_factory([PAGE1])
    rects = SourceLocator(pdf).locate(PAGE1, 1)
    ys = sorted(r["y0"] for r in rects)
    assert len(rects) >= 3 and len(set(ys)) == len(ys)
