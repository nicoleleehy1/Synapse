"""The learning layer: flashcards generated from the graph, scheduled with FSRS.

Cards are made from relationships, not raw text: each one tests a single edge of the
knowledge graph ("What role does X play in Y?") and is grounded in the passage that
edge was extracted from, so the answer can always be checked against the source.
Reviews update each card's FSRS memory state; an entity's mastery is the mean
recall probability of its cards right now, which decays between reviews exactly as
the memory model predicts and is drawn on the graph as a heatmap.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import anthropic
from pydantic import BaseModel, Field

from app.config import settings
from app.services.fsrs import FSRS, Memory, Rating
from app.services.graph_store import GraphStore

logger = logging.getLogger(__name__)

BATCH = 10
DAY_MS = 86_400_000


class _CardDraft(BaseModel):
    fact: int = Field(description="Number of the fact this card tests.")
    front: str = Field(description="A specific question answerable from the fact alone, under 25 words.")
    back: str = Field(description="The answer in one or two sentences, under 45 words.")


class _CardBatch(BaseModel):
    cards: list[_CardDraft]


CARD_SYSTEM = """You write flashcards that help someone learn the material in their documents.

You receive numbered facts. Each fact is a relationship between two entities from a
knowledge graph, with the passage it was extracted from. Write at most one card per fact.

A good card:
- tests one relationship: why, how, or what role, rather than a yes/no question
- names the entities so the question makes sense without context
- has an answer that is fully supported by the passage
- avoids trivia such as page numbers, and doesn't put the answer in the question

Skip a fact if it is trivial, vague, or not supported by its passage."""


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _dt(ms: int | None) -> datetime | None:
    return datetime.fromtimestamp(ms / 1000, tz=UTC) if ms is not None else None


def memory_from_row(row: dict[str, Any]) -> Memory:
    return Memory(
        stability=row.get("stability") or 0.0,
        difficulty=row.get("difficulty") or 0.0,
        state=row.get("state") or "new",
        reps=row.get("reps") or 0,
        lapses=row.get("lapses") or 0,
        last_review=_dt(row.get("last_review_ms")),
        due=_dt(row.get("due_ms")),
    )


class StudyService:
    def __init__(
        self,
        graph_store: GraphStore,
        client: anthropic.AsyncAnthropic | None = None,
        scheduler: FSRS | None = None,
    ) -> None:
        self._gs = graph_store
        self._llm = client or anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key or None)
        self.fsrs = scheduler or FSRS(desired_retention=settings.desired_retention)

    # ── Generation ────────────────────────────────────────────────────────────

    async def generate(self, document_id: str | None, count: int) -> int:
        """Create up to `count` new cards from relationships that don't have one yet."""
        # Ask for more candidates than needed: Claude skips weak facts.
        candidates = [
            c for c in await self._gs.card_candidates(document_id, int(count * 1.5) + 2) if c.get("passage")
        ]
        batches = [candidates[i : i + BATCH] for i in range(0, len(candidates), BATCH)]
        sem = asyncio.Semaphore(settings.extraction_concurrency)

        async def one(batch: list[dict[str, Any]]) -> list[dict[str, Any]]:
            async with sem:
                try:
                    return await self._draft(batch)
                except Exception:  # noqa: BLE001 - one failed batch shouldn't lose the rest
                    logger.exception("Card generation batch failed")
                    return []

        drafted = [c for cards in await asyncio.gather(*(one(b) for b in batches)) for c in cards]
        cards = drafted[:count]
        await self._gs.write_cards(cards)
        logger.info("Generated %d flashcards from %d candidate facts", len(cards), len(candidates))
        return len(cards)

    async def _draft(self, batch: list[dict[str, Any]]) -> list[dict[str, Any]]:
        lines = []
        for i, c in enumerate(batch, 1):
            rel = f"{c['src']} ({c['src_type']}) -[{c['type']}]-> {c['tgt']} ({c['tgt_type']})"
            if c.get("description"):
                rel += f": {c['description']}"
            lines.append(f'<fact n="{i}">\n{rel}\n<passage>{c["passage"]}</passage>\n</fact>')
        kwargs: dict[str, Any] = dict(
            model=settings.llm_model,
            max_tokens=6000,
            system=CARD_SYSTEM,
            messages=[{"role": "user", "content": "\n".join(lines)}],
            output_format=_CardBatch,
            output_config={"effort": settings.extraction_effort},
        )
        if settings.llm_fallbacks:
            resp = await self._llm.beta.messages.parse(
                betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs
            )
        else:
            resp = await self._llm.messages.parse(**kwargs)
        if resp.stop_reason in ("refusal", "max_tokens") or resp.parsed_output is None:
            return []
        now = _ms(datetime.now(UTC))
        out, used = [], set()
        for d in resp.parsed_output.cards:
            if not 1 <= d.fact <= len(batch) or d.fact in used or not d.front.strip() or not d.back.strip():
                continue
            used.add(d.fact)
            c = batch[d.fact - 1]
            out.append(
                {
                    "id": str(uuid.uuid4()),
                    "front": d.front.strip(),
                    "back": d.back.strip(),
                    "relation_id": c["relation_id"],
                    "chunk_id": c["chunk_id"],
                    "document_id": c["document_id"],
                    "entity_ids": [c["src_id"], c["tgt_id"]],
                    "created_ms": now,
                }
            )
        return out

    # ── Reviewing ─────────────────────────────────────────────────────────────

    def _with_intervals(self, row: dict[str, Any], now: datetime) -> dict[str, Any]:
        preview = self.fsrs.preview(memory_from_row(row), now)
        return {
            **row,
            "entity_ids": row.get("entity_ids") or [],
            "due_ms": row.get("due_ms") or _ms(now),
            "intervals": {g: int((m.due - now).total_seconds()) for g, m in preview.items()},
        }

    async def due(self, document_id: str | None, limit: int, now: datetime | None = None) -> list[dict]:
        now = now or datetime.now(UTC)
        rows = await self._gs.due_cards(_ms(now), limit, settings.new_cards_per_session, document_id)
        return [self._with_intervals(r, now) for r in rows]

    async def review(self, card_id: str, rating: int, now: datetime | None = None) -> dict | None:
        now = now or datetime.now(UTC)
        row = await self._gs.get_card(card_id)
        if row is None:
            return None
        before = memory_from_row(row)
        after = self.fsrs.review(before, Rating(rating), now)
        elapsed = (now - before.last_review).total_seconds() / 86400 if before.last_review else 0.0
        await self._gs.record_review(
            card_id,
            memory_row(after),
            {"rating": int(rating), "at_ms": _ms(now), "elapsed_days": round(elapsed, 3)},
        )
        return self._with_intervals({**row, **memory_row(after)}, now)

    # ── Progress ──────────────────────────────────────────────────────────────

    async def mastery(self, now: datetime | None = None) -> list[dict[str, Any]]:
        now = now or datetime.now(UTC)
        acc: dict[str, list[float]] = {}
        due: dict[str, int] = {}
        for row in await self._gs.card_memories():
            p = self.fsrs.recall_probability(memory_from_row(row), now)
            is_due = row["state"] != "new" and (row["due_ms"] or 0) <= _ms(now)
            for eid in row.get("entity_ids") or []:
                acc.setdefault(eid, []).append(p)
                due[eid] = due.get(eid, 0) + int(is_due)
        return [
            {"entity_id": eid, "mastery": round(sum(ps) / len(ps), 4), "cards": len(ps), "due": due[eid]}
            for eid, ps in acc.items()
        ]

    async def stats(self, now: datetime | None = None, tz_offset_minutes: int = 0) -> dict[str, Any]:
        """Counts, 30-day retention, the current daily streak and 14 days of activity.

        Days are counted in the viewer's time zone (`tz_offset_minutes` east of UTC).
        """
        now = now or datetime.now(UTC)
        offset = timedelta(minutes=tz_offset_minutes)
        today = (now + offset).date()

        def day_of(ms: int):
            return (datetime.fromtimestamp(ms / 1000, tz=UTC) + offset).date()

        cards = await self._gs.card_memories()
        new = sum(1 for c in cards if c["state"] == "new")
        due = sum(1 for c in cards if c["state"] != "new" and (c["due_ms"] or 0) <= _ms(now))
        counts = await self._gs.review_counts(_ms(now - timedelta(days=30)))
        stamps = await self._gs.review_days(_ms(now - timedelta(days=400)))
        per_day: dict = {}
        for ms in stamps:
            d = day_of(ms)
            per_day[d] = per_day.get(d, 0) + 1

        streak, d = 0, today
        if d not in per_day:
            d -= timedelta(days=1)  # today's reviews may not have happened yet
        while d in per_day:
            streak += 1
            d -= timedelta(days=1)

        return {
            "total": len(cards),
            "new": new,
            "due": due,
            "reviewed_today": per_day.get(today, 0),
            "retention_30d": round(counts["passed"] / counts["total"], 4) if counts["total"] else None,
            "streak_days": streak,
            "activity": [per_day.get(today - timedelta(days=i), 0) for i in range(13, -1, -1)],
        }


def memory_row(m: Memory) -> dict[str, Any]:
    return {
        "state": m.state,
        "stability": m.stability,
        "difficulty": m.difficulty,
        "reps": m.reps,
        "lapses": m.lapses,
        "last_review_ms": _ms(m.last_review) if m.last_review else None,
        "due_ms": _ms(m.due) if m.due else None,
    }
