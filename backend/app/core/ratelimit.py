"""Per-IP sliding-window rate limiting for the auth endpoints.

In-memory and per-process — under multiple workers each process keeps its own
window, so the effective limit is (limit × workers). That's acceptable for its
purpose (blunting credential stuffing / brute force); a shared store (Redis)
can replace `_hits` without changing the dependency interface.
"""
import threading
import time
from collections import defaultdict, deque
from typing import Callable, Deque, Dict, Tuple

from fastapi import HTTPException, Request

_hits: Dict[Tuple[str, str], Deque[float]] = defaultdict(deque)
_lock = threading.Lock()


def _client_ip(request: Request) -> str:
    # Honour the first hop of X-Forwarded-For when deployed behind a proxy
    # (Render/Railway terminate TLS in front of uvicorn).
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def rate_limit(bucket: str, limit: int, window_s: int) -> Callable:
    """Dependency factory: at most `limit` requests per `window_s` per client IP."""

    def dependency(request: Request) -> None:
        key = (bucket, _client_ip(request))
        now = time.monotonic()
        with _lock:
            q = _hits[key]
            while q and now - q[0] > window_s:
                q.popleft()
            if len(q) >= limit:
                raise HTTPException(
                    status_code=429,
                    detail="Too many attempts — try again shortly",
                    headers={"Retry-After": str(window_s)},
                )
            q.append(now)

    return dependency
