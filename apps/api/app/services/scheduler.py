"""In-process periodic work (follow-ups, retries).

Started once from the FastAPI startup hook. Runs each registered job on its
own interval in a daemon thread; a job that raises is logged and retried on
the next tick. Durable state lives in the database, never in this module, so
a restart only delays work by at most one interval.

The follow-up engine registers here (see services/rfq/followups.py).
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable, List, Tuple

logger = logging.getLogger("procureai.scheduler")

_JOBS: List[Tuple[str, int, Callable[[], None]]] = []
_THREADS: List[threading.Thread] = []
_STOP = threading.Event()


def register(name: str, interval_s: int, fn: Callable[[], None]) -> None:
    _JOBS.append((name, interval_s, fn))


def _loop(name: str, interval_s: int, fn: Callable[[], None]) -> None:
    while not _STOP.is_set():
        try:
            fn()
        except Exception:  # noqa: BLE001
            logger.exception("scheduled job %s failed", name)
        _STOP.wait(interval_s)


def start() -> None:
    """Idempotent. Safe to call from the startup hook and from tests."""
    if _THREADS:
        return
    _STOP.clear()
    for name, interval_s, fn in _JOBS:
        t = threading.Thread(target=_loop, args=(name, interval_s, fn), name=f"sched-{name}", daemon=True)
        t.start()
        _THREADS.append(t)


def stop() -> None:
    _STOP.set()
    _THREADS.clear()


def run_once() -> None:
    """Tests: run every job synchronously, once."""
    for name, _, fn in _JOBS:
        fn()
