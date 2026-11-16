from __future__ import annotations

import os
import tempfile

# Settings are read at import time: configure before importing the app.
os.environ.setdefault("NEO4J_PASSWORD", os.environ.get("NEO4J_TEST_PASSWORD", "testpassword"))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ["PDF_DIR"] = tempfile.mkdtemp(prefix="synapse-pdfs-")
if os.environ.get("NEO4J_TEST_URI"):
    os.environ["NEO4J_URI"] = os.environ["NEO4J_TEST_URI"]

import pymupdf  # noqa: E402
import pytest  # noqa: E402

from app.services.embeddings import HashEmbedder, set_embedder  # noqa: E402

set_embedder(HashEmbedder())


def make_pdf(path, pages: list[str]) -> None:
    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page()
        page.insert_textbox(pymupdf.Rect(50, 50, 550, 800), text, fontsize=10)
    doc.save(str(path))
    doc.close()


@pytest.fixture
def pdf_factory(tmp_path):
    def _make(pages: list[str], name: str = "doc.pdf"):
        p = tmp_path / name
        make_pdf(p, pages)
        return p

    return _make


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    from app.ratelimit import query_limiter, upload_limiter

    upload_limiter._hits.clear()
    query_limiter._hits.clear()
    yield
