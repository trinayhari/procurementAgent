"""Golden sheet selections — the zero-cost regression check for extraction.

`select_sheets` decides which sheets of a combined set each plan type reads. A
wrong exclusion is invisible downstream (the model simply never sees the sheet)
and it is deterministic, so it is the cheapest extraction regression there is:
no model call, just the PDF text layer. The expectations below are the
ground-truthed selections from the 2026-07-22 fixture session (see memory:
extraction-test-fixtures) plus the ones the eval bench found wrong.

The PDFs are local-only corpus fixtures (gitignored); each case skips when its
PDF is not on this machine. Pure keyword-matching tests at the bottom need
nothing on disk.
"""
import os

import pytest

from app.config import settings
from app.services.extraction import registry, sheets

CORPUS_DOCS = os.path.join(os.path.dirname(__file__), "..", "..", "..", "bench-corpus", "docs")


def _select(doc_file, plan_type, word_boundary):
    path = os.path.join(CORPUS_DOCS, doc_file)
    if not os.path.isfile(path):
        pytest.skip("local-only corpus PDF not present: {}".format(doc_file))
    from app.services.extraction.pdf import extract_text_pages, page_count

    pages = extract_text_pages(path, 60)
    old = settings.sheet_keywords_word_boundary
    settings.sheet_keywords_word_boundary = word_boundary
    try:
        sel = sheets.select_sheets(registry.get(plan_type), pages, page_count(path))
    finally:
        settings.sheet_keywords_word_boundary = old
    return [i + 1 for i in sel.matched_indices], [i + 1 for i in sel.vision_indices]


# (doc, plan_type, expected matched 1-based, expected vision 1-based) under the
# production default (word-boundary matching) — the selections the bench showed
# to be right.
GOLDEN = [
    # 54-61: CS cover, A1-A3 elevations, A4 foundation, A5/A6 floor plans, A7
    # roof, A8 sections, A9-A11 MEP, A12-A14 structural, A15 energy, A16
    # electrical notes, A17 plumbing notes, A18 isometric.
    ("bldg-tx-taylor-northbb-54-61.pdf", "building_plan", [2, 6, 7, 13, 14, 15], [1, 2, 3, 4, 5, 6, 7, 8, 9, 13, 14, 15]),
    ("elec-tx-taylor-northbb-54-61.pdf", "electrical_plan", [11, 12, 17], [1, 3, 4, 5, 8, 9, 11, 12, 17]),
    # Taylor: all sheets A/G-numbered (the 'A' prefix carries no signal);
    # electrical sheets are A121-A123 on pages 13-15.
    ("elec-tx-taylor-buildings.pdf", "electrical_plan", [13, 14, 15], [1, 5, 13, 14, 15, 27]),
    # Portland ADU: page 4 is 'FOUNDATION POST AND BEAM' — the truth's source.
    # Substring matching classified it civil (seven PLATE callouts → 'PLAT').
    ("bldg-or-portland-adu-shed-crawl.pdf", "building_plan", [2, 4, 5, 6, 7, 8], [1, 2, 4, 5, 6, 7, 8]),
    # Four Rivers: page 3 carries the SUMMARY OF QUANTITIES table.
    ("site-il-fourrivers-202-n-main.pdf", "site_plan", [1, 2, 4], [1, 2, 3, 4]),
    # Rolling Meadows: page 8 is E-501 (grounding diagram / test notes).
    ("elec-il-rollingmeadows-generator.pdf", "electrical_plan", [2, 3, 4, 5, 6, 7, 8], [1, 2, 3, 4, 5, 6, 7, 8]),
]


@pytest.mark.parametrize("doc,plan_type,matched,vision", GOLDEN, ids=[g[0] + ":" + g[1] for g in GOLDEN])
def test_sheet_selection_golden(doc, plan_type, matched, vision):
    assert settings.sheet_keywords_word_boundary, "production default flipped back — update the goldens deliberately"
    got_matched, got_vision = _select(doc, plan_type, word_boundary=True)
    assert got_matched == matched, "matched sheets moved"
    assert got_vision == vision, "vision sheets moved"


def test_portland_foundation_sheet_was_skipped_by_the_legacy_matcher():
    """Why the default flipped: the legacy substring matcher drops the truth's only sheet."""
    matched, _ = _select("bldg-or-portland-adu-shed-crawl.pdf", "building_plan", word_boundary=False)
    assert 4 not in matched


# ------------------------------------------------ keyword matching, no PDFs
@pytest.fixture()
def word_boundary():
    old = settings.sheet_keywords_word_boundary
    settings.sheet_keywords_word_boundary = True
    yield
    settings.sheet_keywords_word_boundary = old


def test_plat_does_not_match_plate(word_boundary):
    text = "FOUNDATION PLAN. 2x6 PT SILL PLATE. PLATE WASHER. SILL PLATE ANCHOR."
    assert sheets._scores(text)["civil"] == 0
    assert sheets.classify_page(text) == "structural"


def test_plat_matches_plate_by_substring_in_legacy_mode(monkeypatch):
    monkeypatch.setattr(settings, "sheet_keywords_word_boundary", False)
    text = "FOUNDATION PLAN. 2x6 PT SILL PLATE. PLATE WASHER. SILL PLATE ANCHOR."
    assert sheets._scores(text)["civil"] == 12  # three 'PLAT' × 4


def test_duct_does_not_match_conductor(word_boundary):
    text = "ELECTRICAL. #12 CONDUCTOR, CONDUCTORS IN CONDUIT."
    assert sheets._scores(text)["mechanical"] == 0
    assert sheets._scores(text)["electrical"] > 0


def test_plurals_still_count(word_boundary):
    text = "FLOOR JOISTS, ROOF TRUSSES, STUDS, RAFTERS"
    assert sheets._scores(text)["structural"] == 4


def test_quantity_table_sheet_is_general(word_boundary):
    text = "GENERAL NOTES. SUMMARY OF QUANTITIES. SANITARY SEWER CLEANOUT BACKFLOW."
    assert sheets.classify_page(text) == sheets.GENERAL


def test_sheet_number_breaks_a_family_tie(word_boundary):
    # 'FOUNDATION' (structural 4) vs 'ELECTRICAL' (electrical 4): a dead heat —
    # the E-501 sheet number says electrical.
    text = "E-501 GROUNDING DIAGRAM. ELECTRICAL. CONCRETE FOUNDATION."
    assert sheets.classify_page(text) == "electrical"
