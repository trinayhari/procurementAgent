"""Bench API — the dev-only HTTP surface over `app.eval` (docs/eval-harness.md §3).

Nothing here may make a model call: `extract_document` is replaced with a fake
in every test that starts a run, and conftest force-blanks the provider keys.
The corpus and the bench database are both redirected into tmp_path, so a test
never reads the real corpus or writes the product database.

The three properties worth the most here are the production gate (the bench is
unauthenticated, so it must be impossible to mount in production), serialised
execution (concurrent runs would corrupt each other's variant overlay), and
clean behaviour on a corpus that is not populated yet.
"""
import importlib
import json
import threading
import time

import pytest
from fastapi.testclient import TestClient

from app.api.routes import bench as bench_routes
from app.config import settings
from app.eval import store

TRUTH = {
    "doc_id": "site-test-01",
    "plan_type": "site_plan",
    "completeness": "full",
    "items": [
        {"category": "water", "name": "Fire Hydrant Assembly", "quantity": 3, "unit": "EA"},
        {"category": "water", "name": '8" Gate Valve', "quantity": 4, "unit": "EA"},
    ],
}

HYDRANT_GROUPS = [
    {
        "group": "Water Materials",
        "count": 1,
        "tone": "blue",
        "items": [{"n": "Fire Hydrant Assembly", "q": "3 EA"}],
    }
]


class FakeResult:
    """The subset of ExtractionResult the runner reads."""

    def __init__(self, groups, mocked=False, summary="fake", error=None):
        self.groups = groups
        self.total_items = sum(len(g.get("items", [])) for g in groups)
        self.mocked = mocked
        self.summary = summary
        self.error = error


# ------------------------------------------------------------------ fixtures
def _write_corpus(root):
    (root / "docs").mkdir(parents=True)
    (root / "truth").mkdir()
    (root / "variants").mkdir()
    for doc_id in ("site-test-01", "site-test-02"):
        (root / "docs" / (doc_id + ".pdf")).write_bytes(b"%PDF-1.4\n")
    (root / "truth" / "site-test-01.json").write_text(json.dumps(TRUTH), encoding="utf-8")
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "version": 1,
                "documents": [
                    {
                        "id": doc_id,
                        "title": doc_id,
                        "plan_type": "site_plan",
                        "file": "docs/{}.pdf".format(doc_id),
                        "source_name": "test",
                        "license": "local-only",
                        "truth": "truth/site-test-01.json" if doc_id == "site-test-01" else None,
                    }
                    for doc_id in ("site-test-01", "site-test-02")
                ],
            }
        ),
        encoding="utf-8",
    )


def _isolate(tmp_path, monkeypatch, root):
    monkeypatch.setattr(settings, "bench_corpus_dir", str(root))
    monkeypatch.setattr(settings, "bench_db_url", "sqlite:///" + str(tmp_path / "bench.db"))
    store.reset_engine()


def _drain(timeout=20.0):
    """Wait for the shared worker to finish everything it was given.

    The worker thread is process-global and outlives a test, so a run still in
    flight would execute against the NEXT test's database.
    """
    deadline = time.time() + timeout
    while bench_routes._run_queue.unfinished_tasks and time.time() < deadline:
        time.sleep(0.02)
    assert not bench_routes._run_queue.unfinished_tasks, "bench worker did not drain"


@pytest.fixture()
def bench(tmp_path, monkeypatch):
    """A two-document corpus (one labelled) + an isolated bench database."""
    root = tmp_path / "bench-corpus"
    _write_corpus(root)
    _isolate(tmp_path, monkeypatch, root)
    yield root
    _drain()
    store.reset_engine()


@pytest.fixture()
def empty_bench(tmp_path, monkeypatch):
    """No manifest at all — the corpus track has not landed one on this machine."""
    root = tmp_path / "no-corpus"
    root.mkdir()
    _isolate(tmp_path, monkeypatch, root)
    yield root
    _drain()
    store.reset_engine()


@pytest.fixture()
def api():
    """A TestClient for the bench routes (unauthenticated, no product DB needed)."""
    from app.main import app

    return TestClient(app)


def patch_extraction(monkeypatch, fn):
    monkeypatch.setattr("app.services.extraction.service.extract_document", fn)


def wait_for(api, run_id, statuses, timeout=20.0):
    """Poll the detail endpoint the way the bench app does, until a status lands."""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        response = api.get("/bench/runs/{}".format(run_id))
        assert response.status_code == 200, response.text
        last = response.json()
        if last["status"] in statuses:
            return last
        time.sleep(0.05)
    raise AssertionError("run {} never reached {} (last: {})".format(run_id, statuses, last))


# ------------------------------------------------------------ production gate
def test_bench_routes_are_absent_in_production(api):
    """Even with bench_enabled true. The bench is unauthenticated — this is the wall."""
    import app.main as main_module

    assert any(r.path.startswith("/bench") for r in main_module.app.routes)

    original_env, original_secret = settings.env, settings.jwt_secret
    try:
        settings.env = "production"
        settings.bench_enabled = True
        settings.jwt_secret = "a-real-secret-for-this-test"  # main.py refuses the default
        production = importlib.reload(main_module)
        assert [r.path for r in production.app.routes if r.path.startswith("/bench")] == []
        assert TestClient(production.app).get("/bench/status").status_code == 404
    finally:
        settings.env, settings.jwt_secret = original_env, original_secret
        restored = importlib.reload(main_module)
    assert any(r.path.startswith("/bench") for r in restored.app.routes)


# ------------------------------------------------------------------ read-only
def test_status_reports_coverage_and_that_extraction_would_be_mocked(bench, api):
    body = api.get("/bench/status").json()
    assert body["enabled"] is True
    assert body["corpus_dir"] == str(bench)
    assert body["docs"] == 2 and body["labelled"] == 1 and body["present"] == 2
    assert body["populated"] is True
    # conftest blanks PROCUREAI_OPENAI_API_KEY, so a run here would be mocked.
    assert body["live_extraction"] is False


def test_corpus_lists_documents_with_truth_and_pdf_flags(bench, api):
    body = api.get("/bench/corpus").json()
    assert body["problems"] == []
    docs = {d["id"]: d for d in body["documents"]}
    assert set(docs) == {"site-test-01", "site-test-02"}
    assert docs["site-test-01"]["has_truth"] is True
    assert docs["site-test-02"]["has_truth"] is False
    assert docs["site-test-01"]["exists"] is True


def test_a_missing_pdf_is_reported_not_hidden(bench, api):
    (bench / "docs" / "site-test-02.pdf").unlink()
    docs = {d["id"]: d for d in api.get("/bench/corpus").json()["documents"]}
    assert docs["site-test-02"]["exists"] is False


def test_plan_types_carry_category_keys(api):
    body = api.get("/bench/plan-types").json()
    by_key = {p["key"]: p for p in body}
    assert "site_plan" in by_key
    categories = {c["key"] for c in by_key["site_plan"]["categories"]}
    assert {"water", "sewer", "storm"} <= categories
    assert all(c["tone"] for c in by_key["site_plan"]["categories"])


def test_variants_always_include_baseline(bench, api):
    body = api.get("/bench/variants").json()
    assert body[0]["id"] == "baseline"
    assert body[0]["problems"] == []


def test_an_invalid_variant_file_is_listed_with_its_problems(bench, api):
    (bench / "variants" / "broken.json").write_text(
        json.dumps({"id": "broken", "label": "Broken", "settings": {"not_a_setting": 1}}),
        encoding="utf-8",
    )
    by_id = {v["id"]: v for v in api.get("/bench/variants").json()}
    assert by_id["broken"]["problems"] == ["settings.not_a_setting: not a known setting"]


# --------------------------------------------------------------- empty corpus
def test_an_unpopulated_corpus_gives_clean_empty_responses(empty_bench, api):
    status = api.get("/bench/status")
    assert status.status_code == 200
    assert status.json()["docs"] == 0
    assert status.json()["labelled"] == 0
    assert status.json()["populated"] is False

    corpus_response = api.get("/bench/corpus")
    assert corpus_response.status_code == 200
    body = corpus_response.json()
    assert body["documents"] == []
    assert len(body["problems"]) == 1 and "manifest" in body["problems"][0]

    variants_response = api.get("/bench/variants")
    assert variants_response.status_code == 200
    assert [v["id"] for v in variants_response.json()] == ["baseline"]

    assert api.get("/bench/runs").json() == []


def test_starting_a_run_without_a_corpus_is_a_404_not_a_500(empty_bench, api):
    response = api.post(
        "/bench/runs", json={"doc_ids": ["site-test-01"], "variant_ids": ["baseline"]}
    )
    assert response.status_code == 404
    assert "manifest" in response.json()["detail"]


# ------------------------------------------------------------- run lifecycle
def test_a_run_goes_queued_then_done_and_carries_the_whole_diff(bench, api, monkeypatch):
    patch_extraction(monkeypatch, lambda path, plan_type: FakeResult(HYDRANT_GROUPS))

    response = api.post(
        "/bench/runs",
        json={
            "doc_ids": ["site-test-01"],
            "variant_ids": ["baseline"],
            "trials": 2,
            "notes": "batch-1",
        },
    )
    assert response.status_code == 202, response.text
    created = response.json()
    assert len(created["run_ids"]) == 1
    # Cost is stated up front: 1 doc × 1 variant × 2 trials.
    assert created["extractions"] == 2
    assert (created["docs"], created["variants"], created["trials"]) == (1, 1, 2)

    run_id = created["run_ids"][0]
    run = wait_for(api, run_id, {"done", "failed", "cancelled"})
    assert run["status"] == "done"
    assert run["progress_done"] == run["progress_total"] == 2
    assert run["notes"] == "batch-1"

    summary = run["summary"]
    assert summary["trials_ok"] == 2 and summary["trials_scored"] == 2
    assert summary["mocked"] is False
    assert summary["mocked_metrics"] is None
    assert summary["metrics"]["recall"] == 0.5  # 1 of 2 required truth items
    assert summary["metrics"]["precision"] == 1.0

    trial = run["trials_detail"][0]
    assert trial["status"] == "done" and trial["latency_ms"] is not None
    assert trial["groups"] == HYDRANT_GROUPS
    assert trial["score"]["completeness"] == "full"  # explains a non-null precision
    kinds = {m["kind"] for m in trial["score"]["matches"]}
    assert {"hit", "miss"} <= kinds
    miss = [m for m in trial["score"]["matches"] if m["kind"] == "miss"][0]
    assert miss["truth_name"] == '8" Gate Valve'  # the diff names the item

    # Trial ids are persisted, so they are stable across polls (React keys).
    again = api.get("/bench/runs/{}".format(run_id)).json()
    assert [t["id"] for t in again["trials_detail"]] == [
        t["id"] for t in run["trials_detail"]
    ]
    assert len(set(t["id"] for t in run["trials_detail"])) == 2


def test_partial_truth_says_why_precision_is_null(bench, api, monkeypatch):
    truth = dict(TRUTH, completeness="partial")
    (bench / "truth" / "site-test-01.json").write_text(json.dumps(truth), encoding="utf-8")
    patch_extraction(monkeypatch, lambda path, plan_type: FakeResult(HYDRANT_GROUPS))

    run_id = api.post(
        "/bench/runs", json={"doc_ids": ["site-test-01"], "variant_ids": ["baseline"]}
    ).json()["run_ids"][0]
    run = wait_for(api, run_id, {"done", "failed"})

    score = run["trials_detail"][0]["score"]
    assert score["precision"] is None  # unmeasurable, not zero
    assert score["completeness"] == "partial"
    assert run["summary"]["metrics"]["precision"] is None


def test_the_runs_list_can_badge_mocked_without_fetching_detail(bench, api, monkeypatch):
    patch_extraction(monkeypatch, lambda path, plan_type: FakeResult(HYDRANT_GROUPS, mocked=True))
    run_id = api.post(
        "/bench/runs", json={"doc_ids": ["site-test-01"], "variant_ids": ["baseline"]}
    ).json()["run_ids"][0]
    wait_for(api, run_id, {"done", "failed"})

    row = api.get("/bench/runs").json()[0]
    assert row["id"] == run_id
    assert row["mocked_trials"] == 1
    assert row["summary"]["mocked"] is True
    assert "trials_detail" not in row  # the list stays cheap


def test_one_run_per_variant_and_they_share_the_batch_label(bench, api, monkeypatch):
    (bench / "variants" / "quiet.json").write_text(
        json.dumps({"id": "quiet", "label": "Quiet", "settings": {"text_pass_min_items": 8}}),
        encoding="utf-8",
    )
    patch_extraction(monkeypatch, lambda path, plan_type: FakeResult(HYDRANT_GROUPS))

    created = api.post(
        "/bench/runs",
        json={
            "doc_ids": ["site-test-01", "site-test-02"],
            "variant_ids": ["baseline", "quiet"],
            "notes": "ab",
        },
    ).json()
    assert len(created["run_ids"]) == 2
    assert created["extractions"] == 4

    runs = [wait_for(api, rid, {"done", "failed"}) for rid in created["run_ids"]]
    assert [r["variant_id"] for r in runs] == ["baseline", "quiet"]
    assert all(r["notes"] == "ab" for r in runs)
    assert all(len(r["trials_detail"]) == 2 for r in runs)
    assert {r["id"] for r in api.get("/bench/runs").json()} == set(created["run_ids"])


def test_a_run_queued_behind_another_honestly_reports_queued(bench, api, monkeypatch):
    """Runs are serialised: `apply()` mutates process-global config."""
    started = threading.Event()
    release = threading.Event()

    def blocking(path, plan_type):
        started.set()
        release.wait(15)
        return FakeResult(HYDRANT_GROUPS)

    patch_extraction(monkeypatch, blocking)
    try:
        created = api.post(
            "/bench/runs",
            json={"doc_ids": ["site-test-01"], "variant_ids": ["baseline"]},
        ).json()
        second = api.post(
            "/bench/runs",
            json={"doc_ids": ["site-test-01"], "variant_ids": ["baseline"]},
        ).json()

        assert started.wait(10), "the worker never picked the first run up"
        assert wait_for(api, created["run_ids"][0], {"running"})["status"] == "running"
        # The second run is NOT executing concurrently, and says so.
        behind = api.get("/bench/runs/{}".format(second["run_ids"][0])).json()
        assert behind["status"] == "queued"
        assert behind["summary"] is None
        assert behind["progress_done"] == 0
    finally:
        release.set()

    for run_id in created["run_ids"] + second["run_ids"]:
        assert wait_for(api, run_id, {"done", "failed"})["status"] == "done"


def test_a_mocked_run_is_flagged_and_kept_out_of_the_headline_metrics(bench, api, monkeypatch):
    patch_extraction(monkeypatch, lambda path, plan_type: FakeResult(HYDRANT_GROUPS, mocked=True))
    created = api.post(
        "/bench/runs", json={"doc_ids": ["site-test-01"], "variant_ids": ["baseline"]}
    ).json()
    run = wait_for(api, created["run_ids"][0], {"done", "failed"})

    summary = run["summary"]
    assert summary["mocked"] is True
    assert summary["metrics"] is None  # never presented as accuracy
    assert summary["mocked_metrics"]["recall"] == 0.5  # kept, but separate
    assert summary["note"]
    assert run["trials_detail"][0]["mocked"] is True


def test_an_unlabelled_document_runs_but_reports_undefined_metrics_as_null(
    bench, api, monkeypatch
):
    patch_extraction(monkeypatch, lambda path, plan_type: FakeResult(HYDRANT_GROUPS))
    created = api.post(
        "/bench/runs", json={"doc_ids": ["site-test-02"], "variant_ids": ["baseline"]}
    ).json()
    run = wait_for(api, created["run_ids"][0], {"done", "failed"})

    assert run["status"] == "done"
    assert run["trials_detail"][0]["score"] is None
    # Undefined, not zero.
    assert run["summary"]["metrics"] is None
    assert run["summary"]["trials_unlabelled"] == 1


# --------------------------------------------------------------- cancellation
def test_cancelling_stops_a_run_between_trials(bench, api, monkeypatch):
    started = threading.Event()
    release = threading.Event()

    def blocking(path, plan_type):
        started.set()
        release.wait(15)
        return FakeResult(HYDRANT_GROUPS)

    patch_extraction(monkeypatch, blocking)
    try:
        created = api.post(
            "/bench/runs",
            json={"doc_ids": ["site-test-01", "site-test-02"], "variant_ids": ["baseline"]},
        ).json()
        run_id = created["run_ids"][0]
        assert started.wait(10)
        assert api.post("/bench/runs/{}/cancel".format(run_id)).json() == {"cancelled": True}
    finally:
        release.set()

    run = wait_for(api, run_id, {"cancelled", "done", "failed"})
    assert run["status"] == "cancelled"
    assert len(run["trials_detail"]) == 1  # the in-flight trial finished; no more started
    # A second cancel is a no-op, not an error.
    assert api.post("/bench/runs/{}/cancel".format(run_id)).json() == {"cancelled": False}


def test_cancelling_a_queued_run_stops_it_ever_extracting(bench, api, monkeypatch):
    started = threading.Event()
    release = threading.Event()
    calls = []

    def blocking(path, plan_type):
        calls.append(path)
        started.set()
        release.wait(15)
        return FakeResult(HYDRANT_GROUPS)

    patch_extraction(monkeypatch, blocking)
    try:
        first = api.post(
            "/bench/runs", json={"doc_ids": ["site-test-01"], "variant_ids": ["baseline"]}
        ).json()["run_ids"][0]
        queued = api.post(
            "/bench/runs", json={"doc_ids": ["site-test-01"], "variant_ids": ["baseline"]}
        ).json()["run_ids"][0]
        assert started.wait(10)
        assert api.post("/bench/runs/{}/cancel".format(queued)).json() == {"cancelled": True}
    finally:
        release.set()

    wait_for(api, first, {"done", "failed"})
    run = wait_for(api, queued, {"cancelled", "done", "failed"})
    assert run["status"] == "cancelled"
    assert run["trials_detail"] == []
    assert len(calls) == 1  # only the first run ever extracted


# ------------------------------------------------------------------ refusals
def test_a_run_with_no_documents_is_refused(bench, api):
    response = api.post("/bench/runs", json={"doc_ids": [], "variant_ids": ["baseline"]})
    assert response.status_code == 400
    assert "at least one document" in response.json()["detail"]


def test_a_run_with_no_variants_is_refused(bench, api):
    response = api.post("/bench/runs", json={"doc_ids": ["site-test-01"], "variant_ids": []})
    assert response.status_code == 400


def test_an_invalid_variant_is_a_400_before_any_extraction(bench, api, monkeypatch):
    (bench / "variants" / "broken.json").write_text(
        json.dumps({"id": "broken", "label": "Broken", "settings": {"not_a_setting": 1}}),
        encoding="utf-8",
    )
    calls = []
    patch_extraction(monkeypatch, lambda path, plan_type: calls.append(path))

    response = api.post(
        "/bench/runs", json={"doc_ids": ["site-test-01"], "variant_ids": ["broken"]}
    )
    assert response.status_code == 400
    assert "not a known setting" in response.json()["detail"]
    assert calls == []
    assert api.get("/bench/runs").json() == []  # nothing was even created


def test_an_unknown_variant_is_a_404(bench, api):
    response = api.post(
        "/bench/runs", json={"doc_ids": ["site-test-01"], "variant_ids": ["nope"]}
    )
    assert response.status_code == 404
    # KeyError stringifies to its repr; the message must not arrive re-quoted.
    assert response.json()["detail"] == "Unknown variant 'nope'"


def test_an_unknown_document_is_a_404(bench, api):
    response = api.post(
        "/bench/runs", json={"doc_ids": ["site-test-01", "nope"], "variant_ids": ["baseline"]}
    )
    assert response.status_code == 404
    assert "nope" in response.json()["detail"]


def test_an_unknown_plan_type_override_is_a_400(bench, api):
    response = api.post(
        "/bench/runs",
        json={
            "doc_ids": ["site-test-01"],
            "variant_ids": ["baseline"],
            "plan_type": "martian_plan",
        },
    )
    assert response.status_code == 400


def test_trials_are_bounded(bench, api):
    response = api.post(
        "/bench/runs",
        json={"doc_ids": ["site-test-01"], "variant_ids": ["baseline"], "trials": 500},
    )
    assert response.status_code == 422


def test_unknown_runs_are_404_everywhere(bench, api):
    assert api.get("/bench/runs/nope").status_code == 404
    assert api.post("/bench/runs/nope/cancel").status_code == 404
    assert api.delete("/bench/runs/nope").status_code == 404
    assert api.get("/bench/runs/compare", params={"a": "nope", "b": "also"}).status_code == 404


# -------------------------------------------------------------------- delete
def test_deleting_a_run_removes_it_and_its_trials(bench, api, monkeypatch):
    patch_extraction(monkeypatch, lambda path, plan_type: FakeResult(HYDRANT_GROUPS))
    run_id = api.post(
        "/bench/runs", json={"doc_ids": ["site-test-01"], "variant_ids": ["baseline"]}
    ).json()["run_ids"][0]
    wait_for(api, run_id, {"done", "failed"})

    assert api.delete("/bench/runs/{}".format(run_id)).json() == {"deleted": True}
    assert api.get("/bench/runs/{}".format(run_id)).status_code == 404
    assert api.get("/bench/runs").json() == []


# ------------------------------------------------------------------- compare
def test_compare_reports_deltas_and_which_documents_moved(bench, api, monkeypatch):
    complete = [
        {
            "group": "Water Materials",
            "count": 2,
            "tone": "blue",
            "items": [
                {"n": "Fire Hydrant Assembly", "q": "3 EA"},
                {"n": '8" Gate Valve', "q": "4 EA"},
            ],
        }
    ]
    patch_extraction(monkeypatch, lambda path, plan_type: FakeResult(HYDRANT_GROUPS))
    a = api.post(
        "/bench/runs", json={"doc_ids": ["site-test-01"], "variant_ids": ["baseline"]}
    ).json()["run_ids"][0]
    wait_for(api, a, {"done", "failed"})

    patch_extraction(monkeypatch, lambda path, plan_type: FakeResult(complete))
    b = api.post(
        "/bench/runs", json={"doc_ids": ["site-test-01"], "variant_ids": ["baseline"]}
    ).json()["run_ids"][0]
    wait_for(api, b, {"done", "failed"})

    response = api.get("/bench/runs/compare", params={"a": a, "b": b})
    # /runs/compare must not be captured by /runs/{run_id}.
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["a"]["id"] == a and body["b"]["id"] == b
    assert body["mocked"] is False
    assert body["deltas"]["recall"] == {"a": 0.5, "b": 1.0, "delta": 0.5}

    row = body["per_doc"][0]
    assert row["doc_id"] == "site-test-01"
    assert row["trials_a"] == 1 and row["trials_b"] == 1 and row["mocked"] is False
    # The item-level lists are the point: which material B started finding.
    assert row["a"]["recall"] == 0.5 and row["b"]["recall"] == 1.0
    a_missing = {m["truth_name"] for m in row["a"]["matches"] if m["kind"] == "miss"}
    b_missing = {m["truth_name"] for m in row["b"]["matches"] if m["kind"] == "miss"}
    assert a_missing == {'8" Gate Valve'} and b_missing == set()
    assert row["a"]["completeness"] == "full"


def test_compare_is_reachable_and_not_read_as_a_run_id(bench, api):
    """Route order: /runs/compare is declared before /runs/{run_id}."""
    response = api.get("/bench/runs/compare", params={"a": "nope", "b": "nope"})
    assert response.status_code == 404
    # The 404 came from compare (both ids reported), not from the {run_id} route.
    assert "Unknown run(s)" in response.json()["detail"]


def test_compare_leaves_a_delta_undefined_when_one_side_is_unmeasurable(
    bench, api, monkeypatch
):
    """An unlabelled run has no metrics — the delta is null, never 0.0."""
    patch_extraction(monkeypatch, lambda path, plan_type: FakeResult(HYDRANT_GROUPS))
    a = api.post(
        "/bench/runs", json={"doc_ids": ["site-test-01"], "variant_ids": ["baseline"]}
    ).json()["run_ids"][0]
    b = api.post(
        "/bench/runs", json={"doc_ids": ["site-test-02"], "variant_ids": ["baseline"]}
    ).json()["run_ids"][0]
    wait_for(api, a, {"done", "failed"})
    wait_for(api, b, {"done", "failed"})

    body = api.get("/bench/runs/compare", params={"a": a, "b": b}).json()
    assert body["deltas"]["recall"]["a"] == 0.5
    assert body["deltas"]["recall"]["b"] is None
    assert body["deltas"]["recall"]["delta"] is None
    per_doc = {row["doc_id"]: row for row in body["per_doc"]}
    # The unlabelled document has no score on either side — null, not an empty
    # score object full of zeroes.
    assert per_doc["site-test-02"]["a"] is None
    assert per_doc["site-test-02"]["b"] is None
    assert per_doc["site-test-02"]["trials_b"] == 0
    assert per_doc["site-test-01"]["a"]["recall"] == 0.5
