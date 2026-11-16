"""Small sliding-window rate limiter for the endpoints that spend LLM tokens.

In-memory and per-process: right for a single-instance deployment of a demo.
Swap the store for Redis if the API is ever scaled out.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

from app.config import settings


class SlidingWindowLimiter:
    def __init__(self, limit: int, window_s: float = 3600.0) -> None:
        self.limit = limit
        self.window_s = window_s
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        q = self._hits[key]
        while q and now - q[0] >= self.window_s:
            q.popleft()
        if len(q) >= self.limit:
            retry = int(self.window_s - (now - q[0])) + 1
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit reached ({self.limit}/hour). Try again in {retry}s.",
                headers={"Retry-After": str(retry)},
            )
        q.append(now)


def client_ip(request: Request) -> str:
    if settings.trust_proxy_headers:
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


upload_limiter = SlidingWindowLimiter(settings.uploads_per_hour)
query_limiter = SlidingWindowLimiter(settings.queries_per_hour)


async def limit_uploads(request: Request) -> None:
    upload_limiter.check(client_ip(request))


async def limit_queries(request: Request) -> None:
    query_limiter.check(client_ip(request))
