"""Map text chunks back to rectangles on the PDF page, for source highlighting.

Chunk text is cleaned (ligatures, whitespace, headers removed), so it can't be
found with a plain substring search. Instead the page's words are read with
their bounding boxes and the chunk is aligned against them on normalised tokens:
the first and last few tokens of the chunk anchor the span, and the words in
between are merged into one rectangle per text line. Coordinates are stored as
fractions of the page size, so the viewer can draw them at any zoom.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import pymupdf

ANCHOR = 4  # tokens used to find the start and end of a chunk
_TOKEN = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> list[str]:
    text = unicodedata.normalize("NFKD", text).lower()
    return _TOKEN.findall(text)


@dataclass(frozen=True)
class _Word:
    page: int  # 1-based
    line: tuple[int, int]  # (block, line) on that page
    x0: float
    y0: float
    x1: float
    y1: float
    token: str


class SourceLocator:
    """Reads a PDF's words once, then locates any number of chunks in it."""

    def __init__(self, pdf_path: str | Path) -> None:
        self._words: list[_Word] = []
        self._page_size: dict[int, tuple[float, float]] = {}
        self._page_start: dict[int, int] = {}
        with pymupdf.open(str(pdf_path)) as doc:
            for i, page in enumerate(doc):
                n = i + 1
                self._page_size[n] = (page.rect.width, page.rect.height)
                self._page_start[n] = len(self._words)
                for x0, y0, x1, y1, word, block, line, _ in page.get_text("words"):
                    # One PDF word can hold several tokens ("non-linear", "2023.").
                    for tok in _tokens(word):
                        self._words.append(_Word(n, (block, line), x0, y0, x1, y1, tok))
        self._seq = [w.token for w in self._words]

    def _find(self, needle: list[str], start: int, stop: int) -> int:
        k = len(needle)
        for i in range(start, max(start, stop - k + 1)):
            if self._seq[i : i + k] == needle:
                return i
        return -1

    def locate(self, text: str, page_number: int, max_pages: int = 3) -> list[dict[str, float]]:
        """Rectangles covering `text`, searching from `page_number` over up to `max_pages` pages."""
        toks = _tokens(text)
        if not toks or page_number not in self._page_start:
            return []
        lo = self._page_start[page_number]
        last_page = min(page_number + max_pages - 1, max(self._page_start))
        hi = self._page_start.get(last_page + 1, len(self._words))

        start = end = -1
        for k in range(min(ANCHOR, len(toks)), 0, -1):
            start = self._find(toks[:k], lo, hi)
            if start >= 0:
                break
        if start < 0:
            return []
        for k in range(min(ANCHOR, len(toks)), 0, -1):
            tail = toks[-k:]
            # Search near where the chunk should end; fall back to anywhere after the start.
            guess = start + len(toks) - k
            window = max(10, len(toks) // 5)
            pos = self._find(tail, max(start, guess - window), min(hi, guess + window + k))
            if pos < 0:
                pos = self._find(tail, start, hi)
            if pos >= 0:
                end = pos + k - 1
                break
        if end < start:
            end = min(start + len(toks) - 1, hi - 1)

        lines: dict[tuple[int, tuple[int, int]], list[float]] = {}
        for w in self._words[start : end + 1]:
            key = (w.page, w.line)
            r = lines.get(key)
            if r is None:
                lines[key] = [w.x0, w.y0, w.x1, w.y1]
            else:
                r[0], r[1], r[2], r[3] = min(r[0], w.x0), min(r[1], w.y0), max(r[2], w.x1), max(r[3], w.y1)

        rects = []
        for (page, _), (x0, y0, x1, y1) in lines.items():
            pw, ph = self._page_size[page]
            rects.append(
                {
                    "page": page,
                    "x0": round(x0 / pw, 4),
                    "y0": round(y0 / ph, 4),
                    "x1": round(x1 / pw, 4),
                    "y1": round(y1 / ph, 4),
                }
            )
        return rects
