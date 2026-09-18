"""Corpus loading + validation against a temporary on-disk corpus.

No real corpus is required — the fixtures below build one per test, including
the "not populated at all" case that every machine hits before the corpus lands.
"""
import json
import os

import pytest

from app.config import settings
from app.eval import corpus


@pytest.fixture()
def corpus_root(tmp_path, monkeypatch):
    root = tmp_path / "bench-corpus"
    (root / "docs").mkdir(parents=True)
    (root / "truth").mkdir()
    monkeypatch.setattr(settings, "bench_corpus_dir", str(root))
    return root


def write_manifest(root, documents, version=1):
    (root / "manifest.json").write_text(
        json.dumps({"version": version, "documents": documents}), encoding="utf-8"
    )


def entry(**overrides):
    base = {
        "id": "site-test-01",
        "title": "Test Civil Set",
        "plan_type": "site_plan",
        "file": "docs/site-test-01.pdf",
        "source_name": "City of Example",
        "source_url": "https://example.gov/plans.pdf",
        "license": "public-domain-usgov",
        "retrieved_at": "2026-08-12",
        "sha256": "a" * 64,
        "bytes": 100,
        "pages": 4,
        "has_text_layer": True,
        "tags": ["utilities"],
        "truth": None,
    }
    base.update(overrides)
    return base


TRUTH = {
    "doc_id": "site-test-01",
    "plan_type": "site_plan",
    "completeness": "full",
    "items": [
        {"category": "water", "name": '8" PVC Water Main', "quantity": 1450, "unit": "LF"},
    ],
    "forbidden": [{"name": "silt fence", "why": "legend only"}],
}


# --------------------------------------------------------- absent corpus
def test_missing_corpus_reports_a_problem_instead_of_raising(corpus_root):
    assert corpus.corpus_exists() is False
    problems = corpus.validate_corpus()
    assert len(problems) == 1 and "not populated" in problems[0]
    assert corpus.coverage()["populated"] is False
    with pytest.raises(corpus.CorpusError):
        corpus.load_corpus()


def test_malformed_manifest_is_a_clear_error(corpus_root):
    (corpus_root / "manifest.json").write_text("{not json", encoding="utf-8")
    problems = corpus.validate_corpus()
    assert problems and "unreadable" in problems[0]


# ------------------------------------------------------------- loading
def test_missing_pdf_loads_with_exists_false(corpus_root):
    write_manifest(corpus_root, [entry()])
    docs = corpus.load_corpus()
    assert len(docs) == 1
    doc = docs[0]
    assert doc.exists is False
    assert os.path.isabs(doc.path)
    assert doc.has_truth is False
    assert corpus.load_truth("site-test-01") is None
    assert corpus.validate_corpus() == []


def test_present_pdf_and_truth(corpus_root):
    (corpus_root / "docs" / "site-test-01.pdf").write_bytes(b"%PDF-1.4\n")
    (corpus_root / "truth" / "site-test-01.json").write_text(json.dumps(TRUTH), encoding="utf-8")
    write_manifest(corpus_root, [entry(truth="truth/site-test-01.json")])

    doc = corpus.get_doc("site-test-01")
    assert doc.exists is True and doc.has_truth is True
    truth = corpus.load_truth("site-test-01")
    assert truth.completeness == "full"
    assert truth.items[0].qty_tolerance == corpus.DEFAULT_QTY_TOLERANCE
    assert truth.items[0].required is True
    assert truth.forbidden[0]["name"] == "silt fence"
    assert corpus.validate_corpus() == []
    assert corpus.coverage() == {
        "corpus_dir": str(corpus_root), "documents": 1, "labelled": 1, "present": 1, "populated": True
    }


def test_conventional_truth_path_is_found_without_a_manifest_field(corpus_root):
    (corpus_root / "truth" / "site-test-01.json").write_text(json.dumps(TRUTH), encoding="utf-8")
    write_manifest(corpus_root, [entry()])
    assert corpus.get_doc("site-test-01").has_truth is True
    assert corpus.load_truth("site-test-01") is not None


def test_unknown_doc_raises_keyerror(corpus_root):
    write_manifest(corpus_root, [entry()])
    with pytest.raises(KeyError):
        corpus.get_doc("nope")


# ---------------------------------------------------------- validation
def test_validation_catches_bad_metadata(corpus_root):
    write_manifest(
        corpus_root,
        [
            entry(id="Bad_ID"),
            entry(id="site-test-02", plan_type="not_a_plan_type"),
            entry(id="site-test-03", license="proprietary"),
            entry(id="site-test-04", source_name=None, source_url=None),
            entry(id="site-test-05", sha256="short"),
            entry(id="site-test-01"),
            entry(id="site-test-01"),
        ],
    )
    problems = "\n".join(corpus.validate_corpus())
    assert "^[a-z0-9]" in problems
    assert "not registered" in problems
    assert "license 'proprietary'" in problems
    assert "no provenance" in problems
    assert "sha256" in problems
    assert "duplicate id" in problems


def test_validation_catches_bad_truth(corpus_root):
    bad = {
        "doc_id": "wrong-id",
        "plan_type": "site_plan",
        "completeness": "mostly",
        "items": [
            {"category": "not_a_category", "name": "x", "qty_tolerance": 1.5},
            {"category": "water", "name": ""},
        ],
        "forbidden": [{"why": "no name"}],
    }
    (corpus_root / "truth" / "site-test-01.json").write_text(json.dumps(bad), encoding="utf-8")
    write_manifest(corpus_root, [entry(truth="truth/site-test-01.json")])
    problems = "\n".join(corpus.validate_corpus())
    assert "completeness 'mostly'" in problems
    assert "not a category" in problems
    assert "qty_tolerance" in problems
    assert "missing name" in problems
    assert "does not match" in problems


def test_declared_truth_file_missing_is_a_problem(corpus_root):
    write_manifest(corpus_root, [entry(truth="truth/nope.json")])
    problems = corpus.validate_corpus()
    assert any("truth file missing" in p for p in problems)
    with pytest.raises(corpus.CorpusError):
        corpus.load_truth("site-test-01")


def test_unexpected_manifest_version_is_reported(corpus_root):
    write_manifest(corpus_root, [entry()], version=2)
    assert any("version" in p for p in corpus.validate_corpus())


def test_an_empty_full_truth_is_a_negative_control_not_a_problem(corpus_root):
    """A non-plan document whose correct BOM is nothing: `full` with no items."""
    control = {"doc_id": "site-test-01", "plan_type": "site_plan", "completeness": "full", "items": []}
    (corpus_root / "truth" / "site-test-01.json").write_text(json.dumps(control), encoding="utf-8")
    write_manifest(corpus_root, [entry(truth="truth/site-test-01.json")])
    assert corpus.validate_corpus() == []
    truth = corpus.load_truth("site-test-01")
    assert truth.items == []


def test_an_empty_partial_truth_measures_nothing_and_is_rejected(corpus_root):
    empty = {"doc_id": "site-test-01", "plan_type": "site_plan", "completeness": "partial", "items": []}
    (corpus_root / "truth" / "site-test-01.json").write_text(json.dumps(empty), encoding="utf-8")
    write_manifest(corpus_root, [entry(truth="truth/site-test-01.json")])
    problems = "\n".join(corpus.validate_corpus())
    assert "no items" in problems
