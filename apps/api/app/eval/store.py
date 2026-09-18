"""SQLite persistence for bench runs and trials.

Deliberately isolated from the product database: its own `DeclarativeBase`, its
own engine built from `settings.bench_db_url`, and no import of `app.db`. Eval
data is throwaway experiment output and must never end up in `procureai.db`,
never appear in Alembic's metadata, and never be dropped by a test that clears
the product schema.

The engine is built lazily and re-built when the configured URL changes, so a
test can point the bench at a temp file without importing anything differently.
"""
import json
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional

from sqlalchemy import Boolean, Integer, String, Text, create_engine, func, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.config import settings

STATUSES = ("queued", "running", "done", "failed", "cancelled")


class BenchBase(DeclarativeBase):
    """Declarative base for bench tables ONLY — never app.db.Base."""


class BenchRun(BenchBase):
    __tablename__ = "bench_run"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    finished_at: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="queued")
    variant_id: Mapped[str] = mapped_column(String, nullable=False)
    plan_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    doc_ids: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    trials: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    progress_done: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    progress_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
            "status": self.status,
            "variant_id": self.variant_id,
            "plan_type": self.plan_type,
            "doc_ids": _loads(self.doc_ids) or [],
            "trials": self.trials,
            "notes": self.notes,
            "progress_done": self.progress_done,
            "progress_total": self.progress_total,
            "error": self.error,
            "summary": _loads(self.summary),
        }


class BenchTrial(BenchBase):
    __tablename__ = "bench_trial"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    # Insertion order within a run. Timestamps tie (several trials can start in
    # the same second) and the detail view must list trials in the order they
    # actually ran, so ordering hangs off this rather than started_at.
    seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    run_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    doc_id: Mapped[str] = mapped_column(String, nullable=False)
    variant_id: Mapped[str] = mapped_column(String, nullable=False)
    trial_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String, nullable=False, default="done")
    started_at: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    finished_at: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    groups: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    summary_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # A mocked extraction produces numbers that LOOK like accuracy but are not;
    # the flag rides with the row everywhere so nothing can average it in blind.
    mocked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    score: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "run_id": self.run_id,
            "doc_id": self.doc_id,
            "variant_id": self.variant_id,
            "trial_index": self.trial_index,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "latency_ms": self.latency_ms,
            "error": self.error,
            "groups": _loads(self.groups),
            "summary_text": self.summary_text,
            "mocked": bool(self.mocked),
            "score": _loads(self.score),
        }


# ------------------------------------------------------------------- engine
_engine = None
_sessionmaker = None
_engine_url = None


def _dumps(value) -> Optional[str]:
    if value is None:
        return None
    return json.dumps(value, default=str)


def _loads(raw: Optional[str]):
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _session() -> Session:
    """A session on the bench database, creating the schema on first use."""
    global _engine, _sessionmaker, _engine_url
    url = settings.bench_db_url
    if _engine is None or _engine_url != url:
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        _engine = create_engine(url, connect_args=connect_args, future=True)
        _sessionmaker = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False, future=True)
        _engine_url = url
        BenchBase.metadata.create_all(bind=_engine)
    return _sessionmaker()


def reset_engine() -> None:
    """Drop the cached engine — used by tests that repoint `bench_db_url`."""
    global _engine, _sessionmaker, _engine_url
    if _engine is not None:
        _engine.dispose()
    _engine = _sessionmaker = _engine_url = None


# -------------------------------------------------------------------- runs
def create_run(*, variant_ids, doc_ids, plan_type, trials, notes) -> List[str]:
    """One queued run row per variant, all sharing `notes` as the batch label.

    Returns the run ids in variant order. (The contract sketched `-> str`; a run
    is per-variant and the API returns `run_ids[]`, so this returns the list —
    see docs/eval-harness.md.)
    """
    variant_ids = list(variant_ids or [])
    doc_ids = list(doc_ids or [])
    if not variant_ids:
        raise ValueError("A run needs at least one variant")
    if not doc_ids:
        raise ValueError("A run needs at least one document")
    trials = max(1, int(trials or 1))

    created = _now()
    ids: List[str] = []
    with _session() as db:
        for variant_id in variant_ids:
            run_id = uuid.uuid4().hex
            db.add(
                BenchRun(
                    id=run_id,
                    created_at=created,
                    status="queued",
                    variant_id=variant_id,
                    plan_type=plan_type,
                    doc_ids=_dumps(doc_ids),
                    trials=trials,
                    notes=notes,
                    progress_done=0,
                    progress_total=len(doc_ids) * trials,
                )
            )
            ids.append(run_id)
        db.commit()
    return ids


def get_run(run_id: str) -> Optional[dict]:
    """The run plus its trials (the detail view's whole payload), or None."""
    with _session() as db:
        row = db.get(BenchRun, run_id)
        if row is None:
            return None
        data = row.to_dict()
        data["trials_detail"] = [t.to_dict() for t in _trial_rows(db, run_id)]
        return data


def list_trials(run_id: str) -> List[dict]:
    with _session() as db:
        return [t.to_dict() for t in _trial_rows(db, run_id)]


def _trial_rows(db: Session, run_id: str) -> List[BenchTrial]:
    return list(
        db.scalars(
            select(BenchTrial).where(BenchTrial.run_id == run_id).order_by(BenchTrial.seq)
        ).all()
    )


def list_runs(limit: int = 50) -> List[dict]:
    """Recent runs, newest first. Summary only — no trial rows."""
    with _session() as db:
        rows = db.scalars(
            select(BenchRun).order_by(BenchRun.created_at.desc(), BenchRun.id.desc()).limit(limit)
        ).all()
        return [r.to_dict() for r in rows]


def delete_run(run_id: str) -> bool:
    with _session() as db:
        row = db.get(BenchRun, run_id)
        if row is None:
            return False
        for trial in _trial_rows(db, run_id):
            db.delete(trial)
        db.delete(row)
        db.commit()
        return True


def cancel_run(run_id: str) -> bool:
    """Mark a queued/running run cancelled; the runner stops between trials."""
    with _session() as db:
        row = db.get(BenchRun, run_id)
        if row is None or row.status not in ("queued", "running"):
            return False
        row.status = "cancelled"
        row.finished_at = _now()
        db.commit()
        return True


def run_status(run_id: str) -> Optional[str]:
    with _session() as db:
        row = db.get(BenchRun, run_id)
        return row.status if row else None


def start_run(run_id: str, total: int) -> None:
    with _session() as db:
        row = db.get(BenchRun, run_id)
        if row is None:
            raise KeyError("Unknown run '{}'".format(run_id))
        row.status = "running"
        row.progress_total = total
        row.progress_done = 0
        db.commit()


def append_trial(run_id: str, trial: dict) -> None:
    with _session() as db:
        seq = db.scalar(
            select(func.count()).select_from(BenchTrial).where(BenchTrial.run_id == run_id)
        )
        db.add(
            BenchTrial(
                id=trial.get("id") or uuid.uuid4().hex,
                seq=int(seq or 0),
                run_id=run_id,
                doc_id=str(trial.get("doc_id") or ""),
                variant_id=str(trial.get("variant_id") or ""),
                trial_index=int(trial.get("trial_index") or 0),
                status=str(trial.get("status") or "done"),
                started_at=trial.get("started_at"),
                finished_at=trial.get("finished_at"),
                latency_ms=trial.get("latency_ms"),
                error=trial.get("error"),
                groups=_dumps(trial.get("groups")),
                summary_text=trial.get("summary_text"),
                mocked=bool(trial.get("mocked")),
                score=_dumps(trial.get("score")),
            )
        )
        db.commit()


def update_trial_score(trial_id: str, score: Optional[dict], error: Optional[str] = None) -> bool:
    """Replace one trial's stored score (a re-score with a newer scorer / truth)."""
    with _session() as db:
        row = db.get(BenchTrial, trial_id)
        if row is None:
            return False
        row.score = _dumps(score)
        if error is not None:
            row.error = error
        db.commit()
        return True


def update_summary(run_id: str, summary: Optional[dict]) -> bool:
    with _session() as db:
        row = db.get(BenchRun, run_id)
        if row is None:
            return False
        row.summary = _dumps(summary)
        db.commit()
        return True


def update_progress(run_id: str, done: int, total: int) -> None:
    with _session() as db:
        row = db.get(BenchRun, run_id)
        if row is None:
            return
        row.progress_done = int(done)
        row.progress_total = int(total)
        db.commit()


def finish_run(run_id: str, *, status: str, summary: Optional[dict], error: Optional[str] = None) -> None:
    if status not in STATUSES:
        raise ValueError("Unknown run status '{}'".format(status))
    with _session() as db:
        row = db.get(BenchRun, run_id)
        if row is None:
            return
        row.status = status
        row.finished_at = _now()
        row.summary = _dumps(summary)
        row.error = error
        db.commit()


def stats() -> Dict[str, int]:
    with _session() as db:
        return {
            "runs": len(db.scalars(select(BenchRun.id)).all()),
            "trials": len(db.scalars(select(BenchTrial.id)).all()),
        }
