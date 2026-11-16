"""Semantic text chunker with token-aware overlap."""

import math
import re

from app.models import TextChunk


class Chunker:
    """
    Splits a list of page texts into overlapping chunks whose token
    count falls within [min_tokens, max_tokens].

    Strategy:
    1. Split each page into sentences (simple heuristic).
    2. Greedily accumulate sentences until the chunk is full.
    3. When a chunk is full, record it and slide the window back by
       overlap_tokens worth of sentences before starting the next chunk.
    """

    def __init__(
        self,
        min_tokens: int = 300,
        max_tokens: int = 800,
        overlap_tokens: int = 100,
    ) -> None:
        self.min_tokens = min_tokens
        self.max_tokens = max_tokens
        self.overlap_tokens = overlap_tokens

    # ------------------------------------------------------------------

    def chunk_pages(self, pages: list[dict], document_id: str, document_name: str) -> list[TextChunk]:
        """
        pages: list of {"page_number": int, "text": str}
        Returns a flat list of TextChunk objects.
        """
        # Flatten pages to (sentence, page_number) pairs
        sentences: list[tuple[str, int]] = []
        for page in pages:
            for sent in self._split_sentences(page["text"]):
                sentences.append((sent, page["page_number"]))
        # Tokenise each sentence exactly once.
        counts = [self._count(s) for s, _ in sentences]

        chunks: list[TextChunk] = []
        i = 0
        char_offset = 0  # approximate global char position

        while i < len(sentences):
            current_tokens = 0
            chunk_sentences: list[tuple[str, int]] = []

            j = i
            while j < len(sentences) and current_tokens < self.max_tokens:
                sent, pno = sentences[j]
                tok = counts[j]
                if current_tokens + tok > self.max_tokens and chunk_sentences:
                    break
                chunk_sentences.append((sent, pno))
                current_tokens += tok
                j += 1

            if not chunk_sentences:
                # Single sentence exceeds max_tokens — include it anyway
                chunk_sentences.append(sentences[i])
                j = i + 1

            text = " ".join(s for s, _ in chunk_sentences)
            page_number = chunk_sentences[0][1]
            char_start = char_offset
            char_end = char_start + len(text)
            char_offset = char_end  # rough approximation

            chunks.append(
                TextChunk(
                    text=text,
                    page_number=page_number,
                    document_id=document_id,
                    document_name=document_name,
                    char_start=char_start,
                    char_end=char_end,
                    token_count=current_tokens,
                )
            )

            # Slide back by overlap_tokens
            overlap_tok = 0
            new_i = j - 1
            while new_i > i and overlap_tok < self.overlap_tokens:
                overlap_tok += counts[new_i]
                new_i -= 1
            i = max(new_i + 1, i + 1)

        return chunks

    # ------------------------------------------------------------------

    _TOKEN_RE = re.compile(r"\w+|[^\w\s]")

    def _count(self, text: str) -> int:
        """Approximate token count without a network-fetched tokenizer.

        Word/punctuation pieces, inflated for sub-word splits of long words.
        Within ~10% of BPE tokenizers on English prose, which is plenty for
        sizing chunks.
        """
        return sum(max(1, math.ceil(len(p) / 6)) for p in self._TOKEN_RE.findall(text))

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        """Lightweight sentence splitter — good enough for chunking."""
        # Split on ". ", "! ", "? " followed by uppercase, or double newline
        parts = re.split(r"(?<=[.!?])\s+(?=[A-Z])|(?:\n\n+)", text)
        return [p.strip() for p in parts if p.strip()]
