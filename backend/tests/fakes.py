"""Test doubles for the Anthropic client."""

from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any


class FakeMessages:
    def __init__(self, parse_fn: Callable[[dict], Any] | None = None, text: str = "Answer [1].") -> None:
        self.calls: list[dict] = []
        self._parse_fn = parse_fn
        self._text = text

    async def parse(self, **kwargs):
        self.calls.append(kwargs)
        out = self._parse_fn(kwargs) if self._parse_fn else None
        if isinstance(out, Exception):
            raise out
        if isinstance(out, SimpleNamespace):  # full response override
            return out
        return SimpleNamespace(stop_reason="end_turn", parsed_output=out)

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            stop_reason="end_turn", content=[SimpleNamespace(type="text", text=self._text)]
        )


class FakeAnthropic:
    def __init__(self, **kw) -> None:
        self.messages = FakeMessages(**kw)
        self.beta = SimpleNamespace(messages=self.messages)
