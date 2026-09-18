"""CLI behaviour — including the machine this runs on having no corpus at all.

The corpus is gitignored and owned by another track, so `corpus`, `validate` and
`variants` must say what is missing rather than traceback.
"""
import json

import pytest

from app.config import settings
from app.eval import store
from app.eval.__main__ import main

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
    "items": [{"category": "water", "name": "Fire Hydrant Assembly", "quantity": 3, "unit": "EA"}],
}


class FakeResult:
    """The subset of ExtractionResult the runner reads — no model call anywhere."""

    def __init__(self, groups, mocked=False, summary="fake", error=None):
        self.groups = groups
        self.total_items = sum(len(g.get("items", [])) for g in groups)
        self.mocked = mocked
        self.summary = summary
        self.error = error


@pytest.fixture()
def empty_corpus(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "bench_corpus_dir", str(tmp_path / "nothing-here"))
    monkeypatch.setattr(settings, "bench_db_url", "sqlite:///" + str(tmp_path / "bench.db"))
    store.reset_engine()
    yield
    store.reset_engine()


@pytest.fixture()
def populated(tmp_path, monkeypatch):
    root = tmp_path / "bench-corpus"
    (root / "docs").mkdir(parents=True)
    (root / "truth").mkdir()
    (root / "variants").mkdir()
    (root / "docs" / "site-test-01.pdf").write_bytes(b"%PDF-1.4\n")
    (root / "truth" / "site-test-01.json").write_text(json.dumps(TRUTH), encoding="utf-8")
    (root / "variants" / "strict.json").write_text(
        json.dumps({"id": "strict", "label": "Strict", "settings": {"text_pass_min_items": 8}}),
        encoding="utf-8",
    )
    (root / "manifest.json").write_text(
        json.dumps({
            "version": 1,
            "documents": [{
                "id": "site-test-01", "title": "Test Set", "plan_type": "site_plan",
                "file": "docs/site-test-01.pdf", "source_name": "test",
                "license": "local-only", "truth": "truth/site-test-01.json",
            }],
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "bench_corpus_dir", str(root))
    monkeypatch.setattr(settings, "bench_db_url", "sqlite:///" + str(tmp_path / "bench.db"))
    store.reset_engine()
    monkeypatch.setattr(
        "app.services.extraction.service.extract_document",
        lambda path, plan_type: FakeResult(HYDRANT_GROUPS),
    )
    yield root
    store.reset_engine()


# ----------------------------------------------------- graceful degradation
@pytest.mark.parametrize("command", ["corpus", "validate", "variants"])
def test_read_only_commands_survive_an_absent_corpus(empty_corpus, capsys, command):
    assert main([command]) == 0
    out = capsys.readouterr().out
    assert out.strip()
    assert "Traceback" not in out


def test_absent_corpus_json_output_is_still_json(empty_corpus, capsys):
    assert main(["corpus", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["documents"] == []
    assert "not populated" in payload["problem"] or "No corpus manifest" in payload["problem"]

    assert main(["validate", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["populated"] is False


def test_runs_with_no_history_says_so(empty_corpus, capsys):
    assert main(["runs"]) == 0
    assert "no runs yet" in capsys.readouterr().out


def test_run_without_docs_is_an_error_not_run_everything(populated, capsys):
    assert main(["run", "--variant", "baseline"]) == 2
    assert "--docs is required" in capsys.readouterr().out
    assert store.list_runs() == []


def test_run_rejects_unknown_docs_and_variants(populated, capsys):
    assert main(["run", "--docs", "ghost"]) == 2
    assert "unknown document" in capsys.readouterr().out
    assert main(["run", "--docs", "site-test-01", "--variant", "ghost"]) == 2
    assert "Unknown variant" in capsys.readouterr().out


# ---------------------------------------------------------- populated corpus
def test_corpus_and_validate_on_a_good_corpus(populated, capsys):
    assert main(["corpus"]) == 0
    out = capsys.readouterr().out
    assert "site-test-01" in out and "1 document(s) · 1 labelled" in out
    assert main(["validate"]) == 0
    assert "valid" in capsys.readouterr().out


def test_validate_exits_nonzero_on_a_broken_corpus(populated, capsys):
    (populated / "manifest.json").write_text(
        json.dumps({"version": 1, "documents": [{"id": "Bad_ID"}]}), encoding="utf-8"
    )
    assert main(["validate"]) == 1
    assert "problem(s)" in capsys.readouterr().out


def test_variants_lists_disk_variants_with_baseline(populated, capsys):
    assert main(["variants"]) == 0
    out = capsys.readouterr().out
    assert "baseline" in out and "strict" in out


def test_run_then_show_then_compare(populated, capsys):
    assert main(["run", "--docs", "site-test-01", "--variant", "baseline,strict"]) == 0
    out = capsys.readouterr().out
    assert "2 extraction(s): 1 doc(s) × 2 variant(s) × 1 trial(s)" in out
    assert "precision 1.000" in out

    runs = store.list_runs()
    assert len(runs) == 2

    assert main(["runs"]) == 0
    assert "baseline" in capsys.readouterr().out

    assert main(["show", runs[0]["id"], "--json"]) == 0
    detail = json.loads(capsys.readouterr().out)
    assert detail["trials_detail"][0]["score"]["recall"] == 1.0

    assert main(["compare", runs[0]["id"], runs[1]["id"]]) == 0
    out = capsys.readouterr().out
    assert "+0.000" in out  # identical fake extraction → no movement

    assert main(["show", "nope"]) == 2
    assert main(["compare", "nope", "nah"]) == 2


def test_no_subcommand_prints_help(capsys):
    assert main([]) == 0
    assert "usage" in capsys.readouterr().out.lower()
