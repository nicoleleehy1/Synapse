"""PDF text extraction using PyMuPDF."""

import re
import uuid
from pathlib import Path

import fitz  # PyMuPDF


class PDFProcessor:
    """Extracts clean, structured text from PDF files."""

    # Heuristics for stripping common header/footer patterns
    _HEADER_FOOTER_RE = re.compile(
        r"^\s*(?:page\s+\d+\s*(?:of\s+\d+)?|"
        r"\d+\s*/\s*\d+|"
        r"confidential|draft|©.*?\d{4})\s*$",
        re.IGNORECASE | re.MULTILINE,
    )

    def extract(self, pdf_path: str | Path) -> list[dict]:
        """
        Return a list of page dicts:
            {"page_number": int, "text": str}
        Text is cleaned of ligatures, excessive whitespace, and
        probable header/footer lines.
        """
        pdf_path = Path(pdf_path)
        pages: list[dict] = []

        with fitz.open(str(pdf_path)) as doc:
            for page_index, page in enumerate(doc):
                raw = page.get_text("text")  # plain text with line breaks
                cleaned = self._clean(raw)
                if cleaned.strip():
                    pages.append({
                        "page_number": page_index + 1,
                        "text": cleaned,
                    })

        return pages

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _clean(self, text: str) -> str:
        # Normalise ligatures (fi, fl, ff, etc.)
        ligatures = {
            "\ufb00": "ff", "\ufb01": "fi", "\ufb02": "fl",
            "\ufb03": "ffi", "\ufb04": "ffl", "\u2019": "'",
            "\u2018": "'", "\u201c": '"', "\u201d": '"',
            "\u2013": "-", "\u2014": "--",
        }
        for lig, replacement in ligatures.items():
            text = text.replace(lig, replacement)

        # Remove header/footer lines
        text = self._HEADER_FOOTER_RE.sub("", text)

        # Collapse runs of blank lines to a single blank line
        text = re.sub(r"\n{3,}", "\n\n", text)

        # Strip leading/trailing whitespace per line
        lines = [line.rstrip() for line in text.splitlines()]
        text = "\n".join(lines)

        return text.strip()
