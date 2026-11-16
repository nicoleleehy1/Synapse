from datetime import UTC, datetime, timedelta

import pytest

from app.services.study import StudyService

NOW = datetime(2026, 3, 10, 18, 0, tzinfo=UTC)
DAY = 86_400_000


def ms(dt):
    return int(dt.timestamp() * 1000)


class FakeStore:
    def __init__(self, cards, reviews):
        self.cards, self.reviews = cards, reviews

    async def card_memories(self):
        return self.cards

    async def review_counts(self, since_ms):
        sel = [r for r in self.reviews if r[0] >= since_ms]
        return {"total": len(sel), "passed": sum(1 for _, g in sel if g > 1)}

    async def review_days(self, since_ms):
        return [t for t, _ in self.reviews if t >= since_ms]


def card(state, stability=0.0, last=None, due=None, ents=("a",)):
    return {
        "id": "x", "state": state, "stability": stability, "entity_ids": list(ents),
        "last_review_ms": ms(last) if last else None, "due_ms": ms(due) if due else ms(NOW),
    }  # fmt: skip


async def test_streak_activity_and_retention_respect_time_zone():
    # Reviews on each of the last three local days (UTC-8), none yet today.
    local = timedelta(hours=-8)
    days = [NOW + local - timedelta(days=d) for d in (1, 2, 3)]
    reviews = [(ms(d - local), 3) for d in days] + [(ms(days[0] - local) + 1000, 1)]
    svc = StudyService(
        FakeStore([card("new"), card("review", 5, NOW - timedelta(days=6), NOW)], reviews), client=object()
    )
    s = await svc.stats(NOW, tz_offset_minutes=-480)
    assert s["streak_days"] == 3
    assert s["reviewed_today"] == 0
    assert s["activity"][-4:] == [1, 1, 2, 0]
    assert s["retention_30d"] == pytest.approx(0.75)
    assert (s["new"], s["due"], s["total"]) == (1, 1, 2)


async def test_mastery_decays_between_reviews():
    fresh = card("review", 10, NOW, NOW + timedelta(days=10), ents=("a", "b"))
    stale = card("review", 2, NOW - timedelta(days=20), NOW - timedelta(days=18), ents=("b",))
    svc = StudyService(FakeStore([fresh, stale, card("new", ents=("c",))], []), client=object())
    m = {row["entity_id"]: row for row in await svc.mastery(NOW)}
    assert m["a"]["mastery"] == 1.0 and m["a"]["due"] == 0
    assert 0.5 < m["b"]["mastery"] < 0.8 and m["b"]["cards"] == 2 and m["b"]["due"] == 1
    assert m["c"]["mastery"] == 0.0
