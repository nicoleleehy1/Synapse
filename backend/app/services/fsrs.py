"""FSRS-5 spaced-repetition scheduler (Free Spaced Repetition Scheduler).

A pure, dependency-free implementation of the memory model used by Anki and other
modern flashcard apps. Each card carries two latent variables:

- stability S: the number of days until recall probability falls to 90%
- difficulty D: 1 (easy) to 10 (hard), how much S grows on each successful review

Recall probability after t days follows a power forgetting curve,
R(t, S) = (1 + F * t / S) ** DECAY, and a review rated Again/Hard/Good/Easy
updates S and D with the published FSRS-5 formulas and default weights
(fitted on hundreds of millions of reviews). The next interval is the time at
which R drops to the desired retention.

Reference: https://github.com/open-spaced-repetition/fsrs4anki/wiki/The-Algorithm
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import IntEnum
from typing import Literal

DEFAULT_WEIGHTS: tuple[float, ...] = (
    0.40255, 1.18385, 3.173, 15.69105, 7.1949, 0.5345, 1.4604, 0.0046, 1.54575, 0.1192,
    1.01925, 1.9395, 0.11, 0.29605, 2.2698, 0.2315, 2.9898, 0.51655, 0.6621,
)  # fmt: skip
DECAY = -0.5
FACTOR = 19 / 81  # chosen so that R(S, S) = 0.9
RELEARN_DELAY = timedelta(minutes=10)
MAX_INTERVAL_DAYS = 36500

CardState = Literal["new", "review", "relearning"]


class Rating(IntEnum):
    AGAIN = 1
    HARD = 2
    GOOD = 3
    EASY = 4


@dataclass(frozen=True)
class Memory:
    stability: float = 0.0
    difficulty: float = 0.0
    state: CardState = "new"
    reps: int = 0
    lapses: int = 0
    last_review: datetime | None = None
    due: datetime | None = None


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


class FSRS:
    def __init__(self, weights: tuple[float, ...] = DEFAULT_WEIGHTS, desired_retention: float = 0.9) -> None:
        if len(weights) != 19:
            raise ValueError("FSRS-5 needs 19 weights")
        if not 0.7 <= desired_retention <= 0.99:
            raise ValueError("desired_retention must be between 0.7 and 0.99")
        self.w = weights
        self.retention = desired_retention

    # ── Model ─────────────────────────────────────────────────────────────────

    @staticmethod
    def retrievability(elapsed_days: float, stability: float) -> float:
        if stability <= 0:
            return 0.0
        return (1 + FACTOR * max(elapsed_days, 0.0) / stability) ** DECAY

    def interval_days(self, stability: float) -> int:
        days = stability / FACTOR * (self.retention ** (1 / DECAY) - 1)
        return int(_clamp(round(days), 1, MAX_INTERVAL_DAYS))

    def _init_stability(self, g: Rating) -> float:
        return max(self.w[g - 1], 0.1)

    def _init_difficulty(self, g: Rating) -> float:
        return self.w[4] - math.exp(self.w[5] * (g - 1)) + 1

    def _next_difficulty(self, d: float, g: Rating) -> float:
        delta = -self.w[6] * (g - 3)
        d_prime = d + delta * (10 - d) / 9  # linear damping near the ceiling
        target = self._init_difficulty(Rating.EASY)
        return _clamp(self.w[7] * target + (1 - self.w[7]) * d_prime, 1, 10)  # mean reversion

    def _recall_stability(self, d: float, s: float, r: float, g: Rating) -> float:
        hard = self.w[15] if g == Rating.HARD else 1.0
        easy = self.w[16] if g == Rating.EASY else 1.0
        growth = math.exp(self.w[8]) * (11 - d) * s ** -self.w[9] * (math.exp(self.w[10] * (1 - r)) - 1)
        return s * (growth * hard * easy + 1)

    def _forget_stability(self, d: float, s: float, r: float) -> float:
        s_f = self.w[11] * d ** -self.w[12] * ((s + 1) ** self.w[13] - 1) * math.exp(self.w[14] * (1 - r))
        return min(s_f, s)

    def _short_term_stability(self, s: float, g: Rating) -> float:
        return s * math.exp(self.w[17] * (g - 3 + self.w[18]))

    # ── Scheduling ────────────────────────────────────────────────────────────

    def review(self, m: Memory, rating: Rating | int, now: datetime) -> Memory:
        """Apply one review at `now` and return the updated memory with its next due date."""
        g = Rating(rating)
        if m.state == "new" or m.last_review is None:
            s, d = self._init_stability(g), _clamp(self._init_difficulty(g), 1, 10)
        else:
            elapsed = (now - m.last_review).total_seconds() / 86400
            d = self._next_difficulty(m.difficulty, g)
            if elapsed < 1:  # reviewed again the same day
                s = self._short_term_stability(m.stability, g)
            else:
                r = self.retrievability(elapsed, m.stability)
                s = (
                    self._forget_stability(m.difficulty, m.stability, r)
                    if g == Rating.AGAIN
                    else self._recall_stability(m.difficulty, m.stability, r, g)
                )
        s = _clamp(s, 0.1, MAX_INTERVAL_DAYS)

        if g == Rating.AGAIN:
            state: CardState = "relearning"
            due = now + RELEARN_DELAY
        else:
            state = "review"
            due = now + timedelta(days=self.interval_days(s))
        return replace(
            m,
            stability=s,
            difficulty=d,
            state=state,
            reps=m.reps + 1,
            lapses=m.lapses + (1 if g == Rating.AGAIN and m.state == "review" else 0),
            last_review=now,
            due=due,
        )

    def preview(self, m: Memory, now: datetime) -> dict[int, Memory]:
        """What each rating would do, for showing intervals on the answer buttons."""
        return {g.value: self.review(m, g, now) for g in Rating}

    def recall_probability(self, m: Memory, now: datetime) -> float:
        """Probability the card is remembered at `now`; 0 for a card never studied."""
        if m.state == "new" or m.last_review is None:
            return 0.0
        return self.retrievability((now - m.last_review).total_seconds() / 86400, m.stability)
