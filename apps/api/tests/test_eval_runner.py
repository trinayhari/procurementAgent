"""Runner semantics: per-trial isolation, mock flagging, cancellation.

`extract_document` is replaced with a fake throughout — nothing here may make a
model call, and the runner's job is the bookkeeping around extraction, not
extraction itself.
"""
import json

import pytest

from app.config import settings
from app.eval import corpus, runner, store, variants


class FakeResult:
    """The subset of ExtractionResult the runner reads."""

    def __init__(self, groups, mocked=False, summary="fake", error=None):
        self.groups = groups
        self.total_items = sum(len(g.get("items", [])) for g in groups)
        self.mocked = mocked
        self.summary = summary
        self.error = error


HYDRANT_GROUPS = [
    {
        "group": "Water Materials",
        "count": 1,
        "tone": "blue",
        "items": [{"n": "Fire Hydrant Assembly", "q": "3 EA"}],
    }
]

TRUTH = {
    "doc_id": "site-test-01",
    "plan_type": "site_plan",
    "completeness": "full",
    "items": [
        {"category": "water", "name": "Fire Hydrant Assembly", "quantity": 3, "unit": "EA"},
    ],
}


@pytest.fixture()
def bench(tmp_path, monkeypatch):
    """A two-document corpus (one labelled) plus an isolated bench database."""
    root = tmp_path / "bench-corpus"
    (root / "docs").mkdir(parents=True)
    (root / "truth").mkdir()
    for doc_id in ("site-test-01", "site-test-02"):
        (root / "docs" / (doc_id + ".pdf")).write_bytes(b"%PDF-1.4\n")
    (root / "truth" / "site-test-01.json").write_text(json.dumps(TRUTH), encoding="utf-8")
    (root / "manifest.json").write_text(
        json.dumps({
            "version": 1,
            "documents": [
                {
                    "id": doc_id, "title": doc_id, "plan_type": "site_plan",
                    "file": "docs/{}.pdf".format(doc_id), "source_name": "test",
                    "license": "local-only",
                    "truth": "truth/site-test-01.json" if doc_id == "site-test-01" else None,
                }
                for doc_id in ("site-test-01", "site-test-02")
            ],
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "bench_corpus_dir", str(root))
    monkeypatch.setattr(settings, "bench_db_url", "sqlite:///" + str(tmp_path / "bench.db"))
    store.reset_engine()
    assert corpus.validate_corpus() == []
    yield root
    store.reset_engine()


def patch_extraction(monkeypatch, fn):
    monkeypatch.setattr("app.services.extraction.service.extract_document", fn)


def make_run(**overrides):
    kwargs = {
        "variant_ids": ["baseline"], "doc_ids": ["site-test-01"],
        "plan_type": None, "trials": 1, "notes": None,
    }
    kwargs.update(overrides)
    return store.create_run(**kwargs)[0]


# ------------------------------------------------------------ happy path
def test_a_scored_run_records_metrics_and_latency(bench, monkeypatch):
    patch_extraction(monkeypatch, lambda path, plan_type: FakeResult(HYDRANT_GROUPS))
    run = runner.execute_run(make_run())

    assert run["status"] == "done"
    assert run["progress_done"] == run["progress_total"] == 1
    summary = run["summary"]
    assert summary["mocked"] is False
    assert summary["metrics"]["recall"] == 1.0
    assert summary["metrics"]["precision"] == 1.0
    assert summary["mocked_metrics"] is None
    trial = run["trials_detail"][0]
    assert trial["status"] == "done" and trial["latency_ms"] is not None
    assert trial["score"]["counts"]["hit"] == 1
    assert trial["groups"] == HYDRANT_GROUPS


def test_progress_callback_reports_each_trial(bench, monkeypatch):
    patch_extraction(monkeypatch, lambda path, plan_type: FakeResult(HYDRANT_GROUPS))
    seen = []
    runner.execute_run(
        make_run(doc_ids=["site-test-01", "site-test-02"], trials=2),
        on_progress=lambda done, total: seen.append((done, total)),
    )
    assert seen == [(1, 4), (2, 4), (3, 4), (4, 4)]


def test_an_unlabelled_document_runs_but_is_not_scored(bench, monkeypatch):
    patch_extraction(monkeypatch, lambda path, plan_type: FakeResult(HYDRANT_GROUPS))
    run = runner.execute_run(make_run(doc_ids=["site-test-02"]))
    assert run["status"] == "done"
    assert run["trials_detail"][0]["score"] is None
    assert run["summary"]["trials_unlabelled"] == 1
    assert run["summary"]["metrics"] is None
    assert run["summary"]["note"]


# --------------------------------------------------------------- mocking
def test_mocked_trials_are_flagged_and_kept_out_of_the_headline_summary(bench, monkeypatch):
    patch_extraction(monkeypatch, lambda path, plan_type: FakeResult(HYDRANT_GROUPS, mocked=True))
    run = runner.execute_run(make_run())

    trial = run["trials_detail"][0]
    assert trial["mocked"] is True
    assert trial["score"] is not None  # recorded…
    summary = run["summary"]
    assert summary["mocked"] is True
    assert summary["trials_mocked"] == 1
    assert summary["metrics"] is None  # …but never averaged in
    assert summary["mocked_metrics"]["recall"] == 1.0
    assert summary["trials_scored"] == 0


# -------------------------------------------------------------- failures
def test_a_failing_document_does_not_lose_the_rest_of_the_run(bench, monkeypatch):
    def flaky(path, plan_type):
        if "site-test-01" in path:
            raise RuntimeError("PyMuPDF exploded")
        return FakeResult(HYDRANT_GROUPS)

    patch_extraction(monkeypatch, flaky)
    run = runner.execute_run(make_run(doc_ids=["site-test-01", "site-test-02"]))

    assert run["status"] == "done"
    failed, ok = run["trials_detail"]
    assert failed["status"] == "failed" and "PyMuPDF exploded" in failed["error"]
    assert ok["status"] == "done"
    assert run["summary"]["trials_failed"] == 1 and run["summary"]["trials_ok"] == 1


def test_an_extraction_error_result_is_a_failed_trial(bench, monkeypatch):
    patch_extraction(monkeypatch, lambda path, plan_type: FakeResult([], error="No pages"))
    run = runner.execute_run(make_run())
    assert run["status"] == "failed"
    assert run["error"] == "every trial failed"
    assert run["trials_detail"][0]["error"] == "No pages"


def test_a_missing_local_pdf_is_a_clear_trial_error(bench, monkeypatch):
    (bench / "docs" / "site-test-01.pdf").unlink()
    patch_extraction(monkeypatch, lambda path, plan_type: FakeResult(HYDRANT_GROUPS))
    run = runner.execute_run(make_run())
    assert "PDF not present locally" in run["trials_detail"][0]["error"]


def test_an_invalid_variant_fails_the_run_before_extracting(bench, monkeypatch):
    calls = []
    patch_extraction(monkeypatch, lambda path, plan_type: calls.append(path))
    monkeypatch.setattr(
        variants, "get_variant",
        lambda vid: variants.Variant(id=vid, label=vid, settings={"nope": 1}),
    )
    run = runner.execute_run(make_run())
    assert run["status"] == "failed"
    assert "not a known setting" in run["error"]
    assert calls == []


def test_unknown_run_id_raises(bench):
    with pytest.raises(KeyError):
        runner.execute_run("nope")


# ---------------------------------------------------------- cancellation
def test_cancellation_stops_between_trials(bench, monkeypatch):
    run_id = make_run(doc_ids=["site-test-01", "site-test-02"], trials=2)

    def cancel_after_first(path, plan_type):
        store.cancel_run(run_id)
        return FakeResult(HYDRANT_GROUPS)

    patch_extraction(monkeypatch, cancel_after_first)
    run = runner.execute_run(run_id)
    assert run["status"] == "cancelled"
    assert len(run["trials_detail"]) == 1  # the in-flight trial finished, no more started
    assert run["summary"]["trials_total"] == 4


def test_an_already_cancelled_run_is_not_executed(bench, monkeypatch):
    run_id = make_run()
    store.cancel_run(run_id)
    calls = []
    patch_extraction(monkeypatch, lambda path, plan_type: calls.append(path))
    run = runner.execute_run(run_id)
    assert run["status"] == "cancelled" and calls == []


# ------------------------------------------------------- variant plumbing
def test_the_variant_overlay_is_live_during_extraction_and_gone_after(bench, monkeypatch):
    seen = {}
    before = settings.text_pass_min_items

    def record(path, plan_type):
        from app.services.extraction import registry
        seen["text_pass_min_items"] = settings.text_pass_min_items
        seen["prefer_vision"] = registry.require("site_plan").prefer_vision
        return FakeResult(HYDRANT_GROUPS)

    patch_extraction(monkeypatch, record)
    monkeypatch.setattr(
        variants, "get_variant",
        lambda vid: variants.Variant(
            id=vid, label=vid,
            settings={"text_pass_min_items": 8},
            spec_overrides={"site_plan": {"prefer_vision": True}},
        ),
    )
    run = runner.execute_run(make_run())
    assert run["status"] == "done"
    assert seen == {"text_pass_min_items": 8, "prefer_vision": True}
    assert settings.text_pass_min_items == before
    from app.services.extraction import registry
    assert registry.require("site_plan").prefer_vision is False


def test_plan_type_override_is_passed_to_extraction(bench, monkeypatch):
    seen = []
    patch_extraction(
        monkeypatch,
        lambda path, plan_type: seen.append(plan_type) or FakeResult(HYDRANT_GROUPS),
    )
    runner.execute_run(make_run(plan_type="building_plan"))
    assert seen == ["building_plan"]


def test_rescore_reuses_the_stored_extraction_against_new_truth(bench, monkeypatch):
    """A truth or scorer change is evaluated on runs already paid for — no model call."""
    calls = []

    def fake(path, plan_type):
        calls.append(path)
        return FakeResult(HYDRANT_GROUPS)

    patch_extraction(monkeypatch, fake)
    (run_id,) = store.create_run(
        variant_ids=["baseline"], doc_ids=["site-test-01"], plan_type=None, trials=1, notes=None
    )
    runner.execute_run(run_id)
    assert store.get_run(run_id)["summary"]["metrics"]["quantity_accuracy"] == 1.0
    assert len(calls) == 1

    # The truth author corrects the count: 4 hydrants, not 3.
    corrected = dict(TRUTH)
    corrected["items"] = [{"category": "water", "name": "Fire Hydrant Assembly", "quantity": 4, "unit": "EA"}]
    (bench / "truth" / "site-test-01.json").write_text(json.dumps(corrected), encoding="utf-8")

    summary = runner.rescore_run(run_id)
    assert len(calls) == 1  # nothing re-extracted
    assert summary["metrics"]["quantity_accuracy"] == 0.0
    assert summary["metrics"]["recall"] == 1.0
    assert summary["rescored_at"]
    run = store.get_run(run_id)
    assert run["summary"]["metrics"]["quantity_accuracy"] == 0.0
    trial = run["trials_detail"][0]
    assert trial["score"]["matches"][0]["quantity_want"] == 4
    assert trial["groups"] == HYDRANT_GROUPS  # the extraction itself is untouched


def test_rescore_unknown_run_raises(bench):
    with pytest.raises(KeyError):
        runner.rescore_run("nope")
