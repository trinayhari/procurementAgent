"""Bench run/trial persistence — and its isolation from the product database."""
import pytest

from app.config import settings
from app.eval import store


@pytest.fixture()
def bench_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "bench_db_url", "sqlite:///" + str(tmp_path / "bench-runs.db"))
    store.reset_engine()
    yield tmp_path / "bench-runs.db"
    store.reset_engine()


def new_run(**overrides):
    kwargs = {
        "variant_ids": ["baseline"],
        "doc_ids": ["site-test-01"],
        "plan_type": None,
        "trials": 1,
        "notes": None,
    }
    kwargs.update(overrides)
    return store.create_run(**kwargs)


# ------------------------------------------------------------- isolation
def test_bench_tables_are_not_the_product_schema(bench_db):
    from app.db import Base as ProductBase

    bench_tables = set(store.BenchBase.metadata.tables)
    assert bench_tables == {"bench_run", "bench_trial"}
    assert bench_tables.isdisjoint(set(ProductBase.metadata.tables))
    assert store.BenchBase is not ProductBase


def test_runs_are_written_to_the_bench_file_only(bench_db):
    from app.db import engine as product_engine
    from sqlalchemy import inspect

    new_run()
    assert bench_db.exists()
    assert "bench_run" not in set(inspect(product_engine).get_table_names())


# ------------------------------------------------------------ lifecycle
def test_one_run_row_per_variant_sharing_a_batch_label(bench_db):
    ids = new_run(variant_ids=["baseline", "strict"], doc_ids=["a", "b"], trials=2, notes="batch-1")
    assert len(ids) == 2 and len(set(ids)) == 2
    runs = store.list_runs()
    assert {r["variant_id"] for r in runs} == {"baseline", "strict"}
    for run in runs:
        assert run["status"] == "queued"
        assert run["doc_ids"] == ["a", "b"]
        assert run["progress_total"] == 4  # docs × trials
        assert run["notes"] == "batch-1"
        assert run["summary"] is None


def test_run_requires_documents_and_variants(bench_db):
    with pytest.raises(ValueError):
        new_run(doc_ids=[])
    with pytest.raises(ValueError):
        new_run(variant_ids=[])


def test_trials_progress_and_finish(bench_db):
    run_id = new_run(doc_ids=["a", "b"])[0]
    store.start_run(run_id, 2)
    assert store.run_status(run_id) == "running"

    store.append_trial(run_id, {
        "doc_id": "a", "variant_id": "baseline", "trial_index": 0, "status": "done",
        "started_at": "2026-08-12T00:00:00+00:00", "latency_ms": 1234,
        "groups": [{"group": "Water Materials", "items": [{"n": "x", "q": "1 EA"}]}],
        "summary_text": "4 sheet(s)", "mocked": True, "score": {"recall": 1.0},
    })
    store.append_trial(run_id, {
        "doc_id": "b", "variant_id": "baseline", "trial_index": 0, "status": "failed",
        "started_at": "2026-08-12T00:00:01+00:00", "error": "boom",
    })
    store.update_progress(run_id, 2, 2)
    store.finish_run(run_id, status="done", summary={"metrics": None, "mocked": True})

    run = store.get_run(run_id)
    assert run["status"] == "done" and run["finished_at"]
    assert run["progress_done"] == 2
    assert run["summary"] == {"metrics": None, "mocked": True}
    trials = run["trials_detail"]
    assert [t["doc_id"] for t in trials] == ["a", "b"]
    assert trials[0]["mocked"] is True
    assert trials[0]["score"] == {"recall": 1.0}
    assert trials[0]["groups"][0]["items"][0]["n"] == "x"
    assert trials[1]["status"] == "failed" and trials[1]["error"] == "boom"
    assert store.list_trials(run_id) == trials


def test_a_real_docscore_round_trips_through_the_json_column(bench_db):
    """The diff view reads matches back out of SQLite — every field must survive."""
    from app.eval import scoring
    from app.eval.corpus import Truth, TruthItem
    from app.services.extraction import registry

    spec = registry.require("site_plan")
    truth = Truth(
        doc_id="site-test-01",
        plan_type="site_plan",
        completeness="full",
        notes=None,
        items=[
            TruthItem(
                category="water", name="Fire Hydrant Assembly", aliases=[], quantity=100,
                unit="EA", qty_tolerance=0.1, required=True, source="Sheet C-4",
            ),
            TruthItem(
                category="water", name='8" Gate Valve', aliases=[], quantity=9, unit="EA",
                qty_tolerance=0.05, required=True, source="Sheet C-5",
            ),
        ],
        forbidden=[{"name": "silt fence", "why": "legend symbol only"}],
    )
    groups = [{
        "group": spec.categories[1].label,  # sewer — deliberately the wrong category
        "count": 3,
        "tone": "green",
        "items": [
            {"n": "Fire Hydrant Assembly", "q": "72 EA"},
            {"n": "Silt Fence", "q": "1 EA"},
            {"n": "Mystery Widget", "q": "1 EA"},
        ],
    }]
    score = scoring.score_document(groups, truth, spec)

    run_id = new_run()[0]
    store.append_trial(run_id, {"doc_id": "site-test-01", "variant_id": "baseline",
                                "score": score.to_dict()})
    stored = store.get_run(run_id)["trials_detail"][0]["score"]

    assert stored["matches"] == [vars(m) for m in score.matches]
    by_kind = {m["kind"]: m for m in stored["matches"]}
    assert by_kind["hit"]["truth_source"] == "Sheet C-4"
    assert by_kind["hit"]["qty_tolerance"] == 0.1
    assert by_kind["hit"]["truth_category"] == "water"
    assert by_kind["hit"]["extracted_category"] == "sewer"
    assert by_kind["forbidden"]["forbidden_why"] == "legend symbol only"
    assert by_kind["miss"]["truth_source"] == "Sheet C-5"
    assert by_kind["extra"]["truth_source"] is None
    assert by_kind["extra"]["forbidden_why"] is None


def test_unknown_status_is_rejected(bench_db):
    run_id = new_run()[0]
    with pytest.raises(ValueError):
        store.finish_run(run_id, status="finished-ish", summary=None)


def test_cancel_only_applies_to_live_runs(bench_db):
    run_id = new_run()[0]
    assert store.cancel_run(run_id) is True
    assert store.run_status(run_id) == "cancelled"
    assert store.cancel_run(run_id) is False  # already terminal
    assert store.cancel_run("nope") is False


def test_delete_removes_the_run_and_its_trials(bench_db):
    run_id = new_run()[0]
    store.append_trial(run_id, {"doc_id": "a", "variant_id": "baseline"})
    assert store.delete_run(run_id) is True
    assert store.get_run(run_id) is None
    assert store.list_trials(run_id) == []
    assert store.delete_run(run_id) is False


def test_get_run_of_unknown_id_is_none(bench_db):
    assert store.get_run("nope") is None
    assert store.run_status("nope") is None


def test_list_runs_is_newest_first_and_limited(bench_db):
    ids = new_run(variant_ids=["v{}".format(i) for i in range(5)])
    listed = store.list_runs(limit=2)
    assert len(listed) == 2
    assert {r["id"] for r in listed}.issubset(set(ids))
