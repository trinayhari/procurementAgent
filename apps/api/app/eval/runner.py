"""Run execution — docs × trials for one variant, scored and persisted.

Deliberately serial. `variants.apply()` mutates process-global config, and the
extraction pipeline already parallelises sheets internally (each in-flight sheet
holds its rendered tiles in memory, which is what bounds peak RAM). A second
layer of concurrency here would both corrupt the overlay and OOM the container,
so trials run one at a time.

Two properties matter more than throughput:
  • one bad document must not lose the rest of the run — a trial that raises is
    recorded `failed` and the run continues;
  • a mocked extraction (no OpenAI key) must never be mistaken for an accuracy
    result — mocked trials are scored and stored, but kept OUT of the headline
    summary and reported separately.
"""
import time
import traceback
import uuid
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

from app.eval import corpus, scoring, store, variants

# How the summary reports itself when there is nothing legitimate to average.
_NO_METRICS_NOTE = "no live, labelled trials — nothing to average"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def execute_run(run_id: str, *, on_progress: Optional[Callable[[int, int], None]] = None) -> dict:
    """Execute a queued run to completion. Returns the finished run dict."""
    run = store.get_run(run_id)
    if run is None:
        raise KeyError("Unknown run '{}'".format(run_id))
    if run["status"] == "cancelled":
        return run

    doc_ids: List[str] = list(run.get("doc_ids") or [])
    trials = max(1, int(run.get("trials") or 1))
    total = len(doc_ids) * trials
    store.start_run(run_id, total)

    try:
        variant = variants.get_variant(run["variant_id"])
    except KeyError as exc:
        store.finish_run(run_id, status="failed", summary=None, error=str(exc))
        return store.get_run(run_id)

    problems = variants.validate_variant(variant)
    if problems:
        store.finish_run(
            run_id,
            status="failed",
            summary=None,
            error="Variant '{}' is invalid: {}".format(variant.id, "; ".join(problems)),
        )
        return store.get_run(run_id)

    live_scores: List[scoring.DocScore] = []
    mocked_scores: List[scoring.DocScore] = []
    done = 0
    counts = {"ok": 0, "failed": 0, "mocked": 0, "unlabelled": 0, "scored": 0}
    latencies: List[int] = []
    cancelled = False

    for doc_id in doc_ids:
        if cancelled:
            break
        for trial_index in range(trials):
            if store.run_status(run_id) == "cancelled":
                cancelled = True
                break

            outcome = _run_trial(run, variant, doc_id, trial_index)
            store.append_trial(run_id, outcome["trial"])
            done += 1
            store.update_progress(run_id, done, total)
            if on_progress is not None:
                try:
                    on_progress(done, total)
                except Exception:  # a reporting callback must never fail the run
                    pass

            if outcome["trial"]["status"] == "failed":
                counts["failed"] += 1
                continue
            counts["ok"] += 1
            if outcome["trial"].get("latency_ms") is not None:
                latencies.append(outcome["trial"]["latency_ms"])
            if outcome["trial"]["mocked"]:
                counts["mocked"] += 1
            if outcome["score"] is None:
                counts["unlabelled"] += 1
            elif outcome["trial"]["mocked"]:
                mocked_scores.append(outcome["score"])
            else:
                counts["scored"] += 1
                live_scores.append(outcome["score"])

    summary = {
        "variant_id": variant.id,
        "trials_total": total,
        "trials_run": done,
        "trials_ok": counts["ok"],
        "trials_failed": counts["failed"],
        "trials_mocked": counts["mocked"],
        "trials_unlabelled": counts["unlabelled"],
        "trials_scored": counts["scored"],
        # True when ANY trial came from the mock path: the caller must show it.
        "mocked": counts["mocked"] > 0,
        "latency_ms_avg": (sum(latencies) / len(latencies)) if latencies else None,
        "metrics": scoring.aggregate(live_scores) if live_scores else None,
        # Kept strictly apart — mock numbers are not accuracy numbers.
        "mocked_metrics": scoring.aggregate(mocked_scores) if mocked_scores else None,
        "note": None if live_scores else _NO_METRICS_NOTE,
    }

    if cancelled:
        store.finish_run(run_id, status="cancelled", summary=summary)
    elif counts["ok"] == 0 and total > 0:
        store.finish_run(
            run_id, status="failed", summary=summary, error="every trial failed"
        )
    else:
        store.finish_run(run_id, status="done", summary=summary)
    return store.get_run(run_id)


def _run_trial(run: dict, variant: variants.Variant, doc_id: str, trial_index: int) -> Dict:
    """One extraction + score. Never raises: failures come back as a failed trial."""
    trial = {
        "id": uuid.uuid4().hex,
        "doc_id": doc_id,
        "variant_id": variant.id,
        "trial_index": trial_index,
        "status": "done",
        "started_at": _now(),
        "finished_at": None,
        "latency_ms": None,
        "error": None,
        "groups": None,
        "summary_text": None,
        "mocked": False,
        "score": None,
    }

    def fail(message: str):
        trial["status"] = "failed"
        trial["error"] = message
        trial["finished_at"] = _now()
        return {"trial": trial, "score": None}

    try:
        doc = corpus.get_doc(doc_id)
    except (KeyError, corpus.CorpusError) as exc:
        return fail(str(exc))
    if not doc.exists:
        return fail(
            "PDF not present locally: {} (corpus PDFs are gitignored; re-fetch it)".format(doc.path)
        )

    plan_type = run.get("plan_type") or doc.plan_type
    try:
        truth = corpus.load_truth(doc_id)
    except corpus.CorpusError as exc:
        return fail(str(exc))

    # Imported here, not at module scope, so `app.eval` stays importable (and
    # unit-testable) without pulling in PyMuPDF and the OpenAI client.
    from app.services.extraction import registry
    from app.services.extraction.service import extract_document

    spec = registry.get(plan_type)
    if spec is None:
        return fail("Unknown plan type '{}' for document '{}'".format(plan_type, doc_id))

    started = time.time()
    try:
        with variants.apply(variant):
            result = extract_document(doc.path, plan_type)
    except Exception as exc:  # one bad document must not lose the run
        trial["latency_ms"] = int((time.time() - started) * 1000)
        return fail("{}: {}".format(type(exc).__name__, exc).strip() or traceback.format_exc())

    trial["latency_ms"] = int((time.time() - started) * 1000)
    trial["finished_at"] = _now()
    trial["groups"] = getattr(result, "groups", None) or []
    trial["summary_text"] = getattr(result, "summary", None)
    trial["mocked"] = bool(getattr(result, "mocked", False))

    error = getattr(result, "error", None)
    if error:
        trial["status"] = "failed"
        trial["error"] = error
        return {"trial": trial, "score": None}

    score = None
    if truth is not None:
        try:
            score = scoring.score_document(trial["groups"], truth, spec)
            trial["score"] = score.to_dict()
        except Exception as exc:
            trial["error"] = "scoring failed: {}: {}".format(type(exc).__name__, exc)
            score = None
    return {"trial": trial, "score": score}


def rescore_run(run_id: str) -> dict:
    """Re-score every stored trial of a run with the CURRENT scorer and truth files.

    The raw extraction (`groups`) is persisted with each trial, so a matcher or
    ground-truth change can be evaluated against every run already paid for
    without a single model call. Rewrites each trial's score and the run's
    summary in place; the extraction itself is untouched. Returns the new
    summary.
    """
    run = store.get_run(run_id)
    if run is None:
        raise KeyError("Unknown run '{}'".format(run_id))
    from app.services.extraction import registry

    live_scores: List[scoring.DocScore] = []
    mocked_scores: List[scoring.DocScore] = []
    rescored = 0
    for trial in store.list_trials(run_id):
        if trial.get("status") != "done":
            continue
        try:
            truth = corpus.load_truth(trial["doc_id"])
        except corpus.CorpusError:
            truth = None
        if truth is None:
            store.update_trial_score(trial["id"], None)
            continue
        plan_type = run.get("plan_type") or truth.plan_type
        spec = registry.get(plan_type)
        try:
            score = scoring.score_document(trial.get("groups") or [], truth, spec)
        except Exception as exc:
            store.update_trial_score(
                trial["id"], None, error="scoring failed: {}: {}".format(type(exc).__name__, exc)
            )
            continue
        store.update_trial_score(trial["id"], score.to_dict())
        rescored += 1
        (mocked_scores if trial.get("mocked") else live_scores).append(score)

    summary = dict(run.get("summary") or {})
    summary.update(
        {
            "variant_id": run["variant_id"],
            "trials_scored": len(live_scores),
            "metrics": scoring.aggregate(live_scores) if live_scores else None,
            "mocked_metrics": scoring.aggregate(mocked_scores) if mocked_scores else None,
            "note": None if live_scores else _NO_METRICS_NOTE,
            "rescored_at": _now(),
        }
    )
    store.update_summary(run_id, summary)
    return summary
