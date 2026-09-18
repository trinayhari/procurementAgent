"""Eval bench routes — the HTTP surface over `app.eval` (see docs/eval-harness.md).

DEV-ONLY and UNAUTHENTICATED. `main.py` mounts this router only when
`settings.bench_enabled` is true, and production forces that off: the bench
reads the local corpus and burns model calls, so it is never exposed publicly.

Everything here is a thin adapter — corpus loading, scoring, variants, and run
execution all live in `app.eval`. Keep the logic there, not here.

Two things this module does own:

  • **Serialised execution.** `variants.apply()` mutates process-global config
    (settings, prompt constants, registry specs). Two runs executing at once
    would silently overwrite each other's overlay and produce results that look
    real and are garbage. So a POST only *queues* a run; one worker thread
    drains the queue and runs them strictly one at a time. A run waiting behind
    another honestly reports `status="queued"` until the worker picks it up.

  • **Refusing a run before it costs anything.** Unknown documents, an unknown
    or invalid variant, an unregistered plan type, and an empty document list
    are all rejected up front — an invalid variant discovered mid-run has
    already paid for a model call.
"""
import logging
import queue
import threading
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

from app.config import settings
from app.eval import corpus, runner, store, variants
from app.eval import __main__ as eval_cli
from app.schemas.bench import (
    BenchStatus,
    CancelResult,
    CompareOut,
    CorpusOut,
    DeleteResult,
    PlanTypeOut,
    RunCreate,
    RunCreated,
    RunDetailOut,
    RunSummaryOut,
    VariantOut,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/bench", tags=["bench"])


# ------------------------------------------------------- serialised execution
# A single worker draining a FIFO queue. NOT a pool: see the module docstring —
# concurrent runs would corrupt each other's variant overlay.
_run_queue: "queue.Queue" = queue.Queue()
_worker_lock = threading.Lock()
_worker: Optional[threading.Thread] = None


def _worker_loop() -> None:
    while True:
        run_id = _run_queue.get()
        try:
            runner.execute_run(run_id)
        except Exception as exc:  # a crashed run must not kill the worker
            logger.exception("Bench run %s crashed", run_id)
            try:
                store.finish_run(
                    run_id,
                    status="failed",
                    summary=None,
                    error="{}: {}".format(type(exc).__name__, exc),
                )
            except Exception:
                logger.exception("Could not record the failure of bench run %s", run_id)
        finally:
            _run_queue.task_done()


def _enqueue(run_id: str) -> None:
    """Queue a run for the worker, starting the worker on first use."""
    global _worker
    with _worker_lock:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_worker_loop, name="bench-runner", daemon=True)
            _worker.start()
        _run_queue.put(run_id)


# --------------------------------------------------------------------- status
@router.get("/status", response_model=BenchStatus)
def status() -> dict:
    """Liveness + whether a run would produce real (non-mocked) numbers."""
    coverage = corpus.coverage()
    return {
        "enabled": settings.bench_enabled,
        "corpus_dir": coverage["corpus_dir"],
        "docs": coverage["documents"],
        "labelled": coverage["labelled"],
        "present": coverage["present"],
        "populated": coverage["populated"],
        "live_extraction": bool(settings.openai_api_key),
    }


# --------------------------------------------------------------------- corpus
@router.get("/corpus", response_model=CorpusOut)
def get_corpus() -> dict:
    """Every corpus document, plus the problems `validate` would report.

    A corpus that is not populated on this machine is an empty list and one
    explanatory problem — not an error. The corpus is gitignored and owned by
    another track, so "not there yet" is a normal state.
    """
    try:
        docs = corpus.load_corpus()
    except corpus.CorpusError as exc:
        return {"documents": [], "problems": [str(exc)]}
    return {"documents": [vars(d) for d in docs], "problems": corpus.validate_corpus()}


# ----------------------------------------------------------------- plan types
@router.get("/plan-types", response_model=List[PlanTypeOut])
def list_plan_types() -> List[dict]:
    """Registered plan types with their category keys — the run panel's selector."""
    from app.services.extraction import registry

    return [
        {
            "key": spec.key,
            "label": spec.label,
            "description": spec.description,
            "enabled": spec.enabled,
            "categories": [
                {"key": c.key, "label": c.label, "tone": c.tone} for c in spec.categories
            ],
        }
        for spec in registry.all_specs()
    ]


# ------------------------------------------------------------------- variants
@router.get("/variants", response_model=List[VariantOut])
def list_variants() -> List[dict]:
    """Every variant on disk, baseline first, each with its validation problems."""
    return [
        dict(v.to_dict(), problems=variants.validate_variant(v))
        for v in variants.load_variants()
    ]


# ----------------------------------------------------------------------- runs
def _completeness(doc_id: str, cache: Dict[str, Optional[str]]) -> Optional[str]:
    """"full"/"partial" from the ground truth, or None if it can't be read now.

    The stored score does not carry it (that is `app.eval.scoring`'s dataclass,
    which we consume rather than own), but the UI needs it to explain a null
    precision. Read defensively: a corpus that moved since the run must not turn
    the detail view into a 500.
    """
    if doc_id in cache:
        return cache[doc_id]
    value = None
    try:
        truth = corpus.load_truth(doc_id)
        value = truth.completeness if truth is not None else None
    except (KeyError, TypeError, ValueError, corpus.CorpusError):
        value = None
    cache[doc_id] = value
    return value


def _with_completeness(
    score: Optional[dict], doc_id: str, cache: Dict[str, Optional[str]]
) -> Optional[dict]:
    if not score:
        return None
    if score.get("completeness"):
        return score  # already carried by the score itself
    enriched = dict(score)
    enriched["completeness"] = _completeness(score.get("doc_id") or doc_id, cache)
    return enriched


def _run_row(run: dict) -> dict:
    """A run as the list view sees it: + `mocked_trials`, so it can badge MOCKED."""
    summary = run.get("summary") or {}
    count = summary.get("trials_mocked")
    out = dict(run)
    out["mocked_trials"] = int(count) if isinstance(count, int) else None
    return out


def _run_detail(run: dict) -> dict:
    """A run with its trials, each score annotated with its truth completeness."""
    cache: Dict[str, Optional[str]] = {}
    out = _run_row(run)
    trials = []
    for trial in run.get("trials_detail") or []:
        row = dict(trial)
        row["score"] = _with_completeness(trial.get("score"), trial.get("doc_id") or "", cache)
        trials.append(row)
    out["trials_detail"] = trials
    return out


def _unique(values: Optional[List[str]]) -> List[str]:
    """Order-preserving de-duplication — a repeated doc id is a repeated bill."""
    seen = set()
    out: List[str] = []
    for value in values or []:
        value = (value or "").strip()
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out


@router.post("/runs", response_model=RunCreated, status_code=202)
def create_runs(body: RunCreate) -> dict:
    """Queue one run per variant. Returns immediately; the worker executes them.

    Everything that can be checked without an extraction is checked here, so a
    bad request costs nothing.
    """
    from app.services.extraction import registry

    doc_ids = _unique(body.doc_ids)
    variant_ids = _unique(body.variant_ids)
    if not doc_ids:
        raise HTTPException(
            status_code=400,
            detail="Select at least one document — there is no 'run everything'.",
        )
    if not variant_ids:
        raise HTTPException(status_code=400, detail="Select at least one variant.")

    if body.plan_type and registry.get(body.plan_type) is None:
        raise HTTPException(
            status_code=400,
            detail="Unknown plan type '{}'. Registered: {}".format(
                body.plan_type, ", ".join(sorted(s.key for s in registry.all_specs()))
            ),
        )

    try:
        known_docs = {d.id for d in corpus.load_corpus()}
    except corpus.CorpusError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    unknown = [d for d in doc_ids if d not in known_docs]
    if unknown:
        raise HTTPException(
            status_code=404, detail="Unknown corpus document(s): {}".format(", ".join(unknown))
        )

    for variant_id in variant_ids:
        try:
            variant = variants.get_variant(variant_id)
        except KeyError:
            # Not str(exc): KeyError stringifies to its repr, quotes and all.
            raise HTTPException(
                status_code=404, detail="Unknown variant '{}'".format(variant_id)
            )
        # Catching this now turns an invalid overlay into a 400 instead of a
        # burnt model call and a run that failed halfway through.
        problems = variants.validate_variant(variant)
        if problems:
            raise HTTPException(
                status_code=400,
                detail="Variant '{}' is invalid: {}".format(variant_id, "; ".join(problems)),
            )

    run_ids = store.create_run(
        variant_ids=variant_ids,
        doc_ids=doc_ids,
        plan_type=body.plan_type,
        trials=body.trials,
        notes=body.notes,
    )
    for run_id in run_ids:
        _enqueue(run_id)

    return {
        "run_ids": run_ids,
        "extractions": len(doc_ids) * len(variant_ids) * body.trials,
        "docs": len(doc_ids),
        "variants": len(variant_ids),
        "trials": body.trials,
    }


@router.get("/runs", response_model=List[RunSummaryOut])
def list_runs(limit: int = Query(default=50, ge=1, le=500)) -> List[dict]:
    """Recent runs, newest first. Summary rows only — no trials."""
    return [_run_row(run) for run in store.list_runs(limit=limit)]


# Declared BEFORE /runs/{run_id} so "compare" is not swallowed as a run id.
@router.get("/runs/compare", response_model=CompareOut)
def compare(a: str = Query(...), b: str = Query(...)) -> dict:
    """Metric deltas between two runs, overall and per document."""
    run_a = store.get_run(a)
    run_b = store.get_run(b)
    missing = [rid for rid, run in ((a, run_a), (b, run_b)) if run is None]
    if missing:
        raise HTTPException(
            status_code=404, detail="Unknown run(s): {}".format(", ".join(missing))
        )
    mocked = bool(
        ((run_a.get("summary") or {}).get("mocked"))
        or ((run_b.get("summary") or {}).get("mocked"))
    )
    return {
        "a": _run_row(run_a),
        "b": _run_row(run_b),
        "deltas": eval_cli.compare_runs(run_a, run_b),
        "per_doc": _per_doc_compare(run_a, run_b),
        "mocked": mocked,
    }


@router.get("/runs/{run_id}", response_model=RunDetailOut)
def get_run(run_id: str) -> dict:
    """One run with its trials, per-doc scores, and match lists (the diff view)."""
    run = store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Unknown run '{}'".format(run_id))
    return _run_detail(run)


@router.post("/runs/{run_id}/cancel", response_model=CancelResult)
def cancel_run(run_id: str) -> dict:
    """Ask a queued/running run to stop. The runner checks between trials."""
    if store.run_status(run_id) is None:
        raise HTTPException(status_code=404, detail="Unknown run '{}'".format(run_id))
    return {"cancelled": store.cancel_run(run_id)}


@router.delete("/runs/{run_id}", response_model=DeleteResult)
def delete_run(run_id: str) -> dict:
    if store.run_status(run_id) is None:
        raise HTTPException(status_code=404, detail="Unknown run '{}'".format(run_id))
    return {"deleted": store.delete_run(run_id)}


# ------------------------------------------------------- per-document compare
def _doc_scores(run: dict, cache: Dict[str, Optional[str]]):
    """Each document's first LIVE scored trial, its live trial count, mocked flag.

    Mocked trials are never returned as a score — a mock is not a measurement —
    but they do set the flag, so the UI can say why a row is empty.
    """
    first: Dict[str, dict] = {}
    counts: Dict[str, int] = {}
    mocked: Dict[str, bool] = {}
    for trial in run.get("trials_detail") or []:
        doc_id = trial.get("doc_id") or ""
        mocked[doc_id] = mocked.get(doc_id, False) or bool(trial.get("mocked"))
        score = trial.get("score")
        if not score or trial.get("mocked"):
            continue
        counts[doc_id] = counts.get(doc_id, 0) + 1
        if doc_id not in first:
            first[doc_id] = _with_completeness(score, doc_id, cache)
    return first, counts, mocked


def _per_doc_compare(run_a: dict, run_b: dict) -> List[dict]:
    """One row per document either run touched, carrying both sides' full scores."""
    cache: Dict[str, Optional[str]] = {}
    a_scores, a_counts, a_mocked = _doc_scores(run_a, cache)
    b_scores, b_counts, b_mocked = _doc_scores(run_b, cache)

    # A's document order first, so a familiar run reads top-down.
    doc_ids: List[str] = []
    for doc_id in (
        list(run_a.get("doc_ids") or [])
        + list(run_b.get("doc_ids") or [])
        + sorted(a_scores)
        + sorted(b_scores)
    ):
        if doc_id and doc_id not in doc_ids:
            doc_ids.append(doc_id)

    return [
        {
            "doc_id": doc_id,
            "a": a_scores.get(doc_id),
            "b": b_scores.get(doc_id),
            "mocked": bool(a_mocked.get(doc_id) or b_mocked.get(doc_id)),
            "trials_a": a_counts.get(doc_id, 0),
            "trials_b": b_counts.get(doc_id, 0),
        }
        for doc_id in doc_ids
    ]
