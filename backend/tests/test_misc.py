import pytest
from fastapi import HTTPException

from app.config import Settings
from app.ratelimit import SlidingWindowLimiter
from app.services.pdf_processor import PDFProcessor


def test_rate_limiter_window():
    lim = SlidingWindowLimiter(limit=2, window_s=60)
    lim.check("ip", now=0)
    lim.check("ip", now=1)
    with pytest.raises(HTTPException) as exc:
        lim.check("ip", now=2)
    assert exc.value.status_code == 429
    assert int(exc.value.headers["Retry-After"]) == 59
    lim.check("ip", now=61)  # first hit has expired
    lim.check("other-ip", now=2)


def test_cors_origins_accept_comma_separated_env(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "https://a.example, b.example,http://localhost:5173")
    assert Settings().cors_origins == ["https://a.example", "https://b.example", "http://localhost:5173"]


def test_pdf_processor_extracts_pages(pdf_factory):
    path = pdf_factory(["First page about graphs.", "", "Third page, page 3 of 3"])
    pages = PDFProcessor().extract(path)
    assert [p["page_number"] for p in pages] == [1, 3]
    assert "graphs" in pages[0]["text"]
