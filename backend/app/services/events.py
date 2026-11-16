"""In-process pub/sub for live ingestion progress (consumed by the SSE endpoint).

Neo4j holds the durable status; this broker only fans out updates to
connected browsers as they happen, so clients don't have to poll.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict

from app.models import DocumentStatus


class ProgressBroker:
    def __init__(self) -> None:
        self._subs: dict[str, set[asyncio.Queue[DocumentStatus]]] = defaultdict(set)

    def subscribe(self, document_id: str) -> asyncio.Queue[DocumentStatus]:
        q: asyncio.Queue[DocumentStatus] = asyncio.Queue(maxsize=256)
        self._subs[document_id].add(q)
        return q

    def unsubscribe(self, document_id: str, q: asyncio.Queue[DocumentStatus]) -> None:
        subs = self._subs.get(document_id)
        if subs:
            subs.discard(q)
            if not subs:
                del self._subs[document_id]

    def publish(self, status: DocumentStatus) -> None:
        for q in list(self._subs.get(status.document_id, ())):
            if q.full():  # slow consumer: drop the oldest, keep the newest
                q.get_nowait()
            q.put_nowait(status)


broker = ProgressBroker()
