from datetime import UTC, datetime, timedelta

import pytest

from app.services.fsrs import DEFAULT_WEIGHTS, FSRS, Memory, Rating

T0 = datetime(2026, 1, 1, tzinfo=UTC)
f = FSRS()


def test_forgetting_curve_hits_desired_retention_at_stability():
    assert f.retrievability(10, 10) == pytest.approx(0.9)
    assert f.retrievability(0, 10) == 1.0
    assert f.retrievability(5, 10) > f.retrievability(20, 10)
    assert f.interval_days(10) == 10  # at 90% retention the interval equals stability


def test_first_review_uses_initial_stability_per_rating():
    out = f.preview(Memory(), T0)
    for g in (Rating.AGAIN, Rating.HARD, Rating.GOOD, Rating.EASY):
        assert out[g].stability == pytest.approx(DEFAULT_WEIGHTS[g - 1])
    assert out[Rating.GOOD].due == T0 + timedelta(days=3)
    assert out[Rating.EASY].due == T0 + timedelta(days=16)
    assert out[Rating.AGAIN].state == "relearning"
    assert out[Rating.AGAIN].due - T0 == timedelta(minutes=10)
    assert out[Rating.EASY].difficulty < out[Rating.GOOD].difficulty < out[Rating.AGAIN].difficulty


def test_successful_reviews_grow_stability_and_order_intervals():
    m = f.review(Memory(), Rating.GOOD, T0)
    now = m.due
    out = f.preview(m, now)
    assert out[Rating.AGAIN].stability < m.stability < out[Rating.HARD].stability
    assert out[Rating.HARD].due <= out[Rating.GOOD].due <= out[Rating.EASY].due
    # Streak of Good reviews on time: intervals keep growing.
    intervals = []
    for _ in range(5):
        prev = m.last_review
        m = f.review(m, Rating.GOOD, m.due)
        intervals.append((m.due - m.last_review).days)
        assert m.last_review > prev
    assert intervals == sorted(intervals) and intervals[-1] > 60


def test_lapse_counts_and_difficulty_stays_in_range():
    m = f.review(Memory(), Rating.GOOD, T0)
    m = f.review(m, Rating.AGAIN, m.due)
    assert m.lapses == 1 and m.state == "relearning"
    for _ in range(30):
        m = f.review(m, Rating.AGAIN, m.due)
    assert 1 <= m.difficulty <= 10
    assert m.lapses == 1  # relearning failures are not new lapses


def test_same_day_review_uses_short_term_stability():
    m = f.review(Memory(), Rating.AGAIN, T0)
    again = f.review(m, Rating.GOOD, T0 + timedelta(minutes=10))
    assert again.stability > m.stability
    assert again.state == "review"


def test_recall_probability_for_new_and_reviewed_cards():
    assert f.recall_probability(Memory(), T0) == 0.0
    m = f.review(Memory(), Rating.GOOD, T0)
    assert f.recall_probability(m, T0) == 1.0
    assert f.recall_probability(m, T0 + timedelta(days=3)) == pytest.approx(
        f.retrievability(3, DEFAULT_WEIGHTS[2])
    )


def test_validates_configuration():
    with pytest.raises(ValueError):
        FSRS(weights=(1.0,))
    with pytest.raises(ValueError):
        FSRS(desired_retention=0.5)
