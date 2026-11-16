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


# ── Scripted streaming client for the agent ──────────────────────────────────


def text_block(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text)


def tool_block(id: str, name: str, input: dict) -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", id=id, name=name, input=input)


class _FakeStream:
    def __init__(self, blocks: list[SimpleNamespace]) -> None:
        self._blocks = blocks

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def __aiter__(self):
        async def gen():
            for b in self._blocks:
                if b.type == "text":
                    for word in b.text.split(" "):
                        yield SimpleNamespace(type="text", text=word + " ")

        return gen()

    async def get_final_message(self):
        has_tools = any(b.type == "tool_use" for b in self._blocks)
        return SimpleNamespace(
            content=self._blocks,
            stop_reason="tool_use" if has_tools else "end_turn",
            usage=SimpleNamespace(input_tokens=100, output_tokens=20),
        )


class ScriptedMessages(FakeMessages):
    """Each call to stream() plays the next scripted turn.

    A turn is a list of blocks, or a callable(kwargs) -> list of blocks so a
    script can react to earlier tool results.
    """

    def __init__(self, turns: list, **kw) -> None:
        super().__init__(**kw)
        self._turns = list(turns)
        self.stream_calls: list[dict] = []

    def stream(self, **kwargs):
        self.stream_calls.append({**kwargs, "messages": list(kwargs["messages"])})
        turn = self._turns.pop(0) if self._turns else [text_block("(script exhausted)")]
        blocks = turn(kwargs) if callable(turn) else turn
        return _FakeStream(blocks)


class ScriptedAnthropic:
    def __init__(self, turns: list, **kw) -> None:
        self.messages = ScriptedMessages(turns, **kw)
        self.beta = SimpleNamespace(messages=self.messages)
