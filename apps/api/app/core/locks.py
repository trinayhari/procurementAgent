"""Process-local, keyed mutual exclusion for "do this exactly once" routes.

Award and RFQ send both issue side effects that must not be duplicated
(purchase orders, supplier emails). Their status checks are check-then-act
against the database, so two overlapping requests — a triple-clicked button,
two tabs, a replayed request — both pass the check and both act. Each such
route takes a non-blocking lock keyed by the entity; the loser answers 409
immediately instead of queueing behind a multi-second email batch.

Process-local is sufficient for the single-process deployment; a multi-worker
deployment would need the status flip itself to move into the database
(SELECT … FOR UPDATE or a unique constraint on the in-flight row).
"""
import threading
from contextlib import contextmanager
from typing import Dict, Iterator

from fastapi import HTTPException

_locks: Dict[str, threading.Lock] = {}
_guard = threading.Lock()


def keyed_lock(key: str) -> threading.Lock:
    """The one lock for `key` (created on first use, never discarded)."""
    with _guard:
        lock = _locks.get(key)
        if lock is None:
            lock = _locks[key] = threading.Lock()
        return lock


@contextmanager
def exclusive(key: str, busy_detail: str) -> Iterator[None]:
    """Hold `key` for the block; raise 409 `busy_detail` if another request holds it."""
    lock = keyed_lock(key)
    if not lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail=busy_detail)
    try:
        yield
    finally:
        lock.release()
