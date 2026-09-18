"""Matcher + metric tests — the part of the bench that decides whether it tells
the truth. Everything here is in-memory: no corpus, no API key, no model call.
"""
import pytest

from app.eval import scoring
from app.eval.corpus import Truth, TruthItem
from app.services.extraction import registry

SPEC = registry.require("site_plan")
WATER = SPEC.categories[0]
SEWER = SPEC.categories[1]
assert WATER.key == "water" and SEWER.key == "sewer"

# The live-corpus regressions below are electrical gear, so they are scored
# under the spec they actually ran under.
ELEC = registry.require("electrical_plan")
EQUIPMENT = ELEC.category("equipment")


def group(category, *items):
    """A BOM group in the exact shape `extraction.service._to_groups` emits."""
    return {
        "group": category.label,
        "count": len(items),
        "tone": category.tone,
        "items": [{"n": name, "q": q} for name, q in items],
    }


def truth(*items, **kwargs):
    return Truth(
        doc_id=kwargs.get("doc_id", "site-test-01"),
        plan_type=kwargs.get("plan_type", "site_plan"),
        completeness=kwargs.get("completeness", "full"),
        notes=None,
        items=list(items),
        forbidden=list(kwargs.get("forbidden", [])),
    )


def item(name, **kwargs):
    return TruthItem(
        category=kwargs.get("category", "water"),
        name=name,
        aliases=kwargs.get("aliases", []),
        quantity=kwargs.get("quantity"),
        unit=kwargs.get("unit"),
        qty_tolerance=kwargs.get("qty_tolerance", 0.05),
        required=kwargs.get("required", True),
        source=kwargs.get("source"),
    )


def kinds(score):
    return sorted(m.kind for m in score.matches)


# ------------------------------------------------------------ normalisation
def test_normalisation_expands_inches_and_keeps_numbers():
    assert scoring.normalize_name('12" DI Pipe') == "12 inch di pipe"
    assert scoring.normalize_name('8"x6" Tee (to hydrant)') == "8 inch x6 inch tee"
    assert scoring.normalize_name("Fire Hydrants") == "fire hydrant"
    assert scoring.normalize_name("45° Bend") == "45 degree bend"


# --------------------------------------------------- THE DIMENSIONAL GATE
SIZE_PAIRS = [
    ('4" PVC Water Main, C900', '6" PVC Water Main, C900'),
    ('6" PVC Water Main, C900', '4" PVC Water Main, C900'),  # and the reverse
    ("12 AWG THHN Copper Conductor", "10 AWG THHN Copper Conductor"),
    ("480V Panelboard", "208V Panelboard"),
    ('8"x8" Tee', '8"x6" Tee'),  # a size PAIR: one 8 cannot satisfy two
    ('8"x6" Tee', '8"x8" Tee'),
]


@pytest.mark.parametrize("a,b", SIZE_PAIRS)
def test_a_different_size_never_matches_however_similar(a, b):
    """These are >0.85-similar strings and completely different materials."""
    assert scoring.token_set_ratio(
        scoring.normalize_name(a), scoring.normalize_name(b)
    ) > 0.85  # the raw fuzzy score WOULD match
    assert scoring.name_similarity(a, b) == 0.0  # the gate refuses it


def test_a_different_size_is_scored_as_a_miss_and_an_extra():
    score = scoring.score_document(
        [group(WATER, ('6" PVC Water Main, C900', "500 LF"))],
        truth(item('4" PVC Water Main, C900', quantity=500, unit="LF")),
        SPEC,
    )
    assert kinds(score) == ["extra", "miss"]
    assert score.recall == 0.0
    assert score.precision == 0.0


def test_extra_spec_detail_on_the_extracted_side_does_not_block():
    """The gate is directional: added detail is not a contradiction."""
    assert scoring.name_similarity("ductile iron pipe", '12" ductile iron pipe') > 0.82


def test_dropped_spec_detail_on_the_extracted_side_does_block():
    """…but an extraction that lost the size has found something vaguer, not this."""
    assert scoring.name_similarity('12" ductile iron pipe', "ductile iron pipe") == 0.0


# ------------------------------------ the three roles a numeral can play
def test_dimensional_numbers_reads_a_numerals_role():
    # Dimensions and spec values gate.
    assert scoring.dimensional_numbers('4" PVC') == {"4": 1}
    assert scoring.dimensional_numbers("Schedule 40 PVC Conduit") == {"40": 1}
    assert scoring.dimensional_numbers('12" DI Pipe, Class 350') == {"12": 1, "350": 1}
    assert scoring.dimensional_numbers("12 AWG Conductor") == {"12": 1}
    assert scoring.dimensional_numbers("480V Panelboard") == {"480": 1}
    assert scoring.dimensional_numbers('8"x6" Tee') == {"8": 1, "6": 1}
    # Model codes and equipment tags do not.
    assert scoring.dimensional_numbers("Lithonia JEBL-30000LM-GL-120V-40K-80CRI") == {}
    assert scoring.dimensional_numbers("Automatic Transfer Switch ATS1") == {}
    assert scoring.dimensional_numbers("Panel MH-3") == {}
    assert scoring.dimensional_numbers("Fixture, IP65") == {}
    # …but they are still recorded, keyed, so like can be compared with like.
    assert scoring.code_values("Panel MH-3") == {"mh": {"3"}}
    assert scoring.code_values("Automatic Transfer Switch ATS1") == {"ats": {"1"}}


def test_a_contradicting_tag_or_model_code_still_blocks():
    """A numeral that identifies a product is not a size — but it is still an identity."""
    assert scoring.name_similarity("Panel MH-3", "Panel MH-4") == 0.0
    assert scoring.name_similarity(
        "Automatic Transfer Switch ATS1", "Automatic Transfer Switch ATS2"
    ) == 0.0
    assert scoring.name_similarity(
        "Lithonia JEBL-30000LM-GL LED High-Bay", "Lithonia JEBL-20000LM-GL LED High-Bay"
    ) == 0.0
    # A code present on only ONE side never blocks — it cannot contradict anything.
    assert scoring.name_similarity("Panel MH-3", "Panel MH-3, 200A") > 0.82


def test_a_short_alias_cannot_smuggle_past_a_contradicted_rating():
    """From the live corpus: a bare `MSB` alias matched an 800A board to a 600A truth.

    Token-set similarity scores a short acronym against any name containing it
    at 1.0, so the alias alone would have carried the match. A value the ITEM
    states anywhere still may not be contradicted.
    """
    t = truth(
        item(
            "Main Switchboard (MSB) with 600A Main Breaker",
            category=EQUIPMENT.key,
            aliases=["main switch board MSB", "600A switchboard", "MSB"],
        ),
        plan_type="electrical_plan",
    )
    wrong = scoring.score_document(
        [group(EQUIPMENT, ("Main Switchboard (MSB), 800A, 480/277V, 3-phase", "1 EA"))],
        t,
        ELEC,
    )
    assert kinds(wrong) == ["extra", "miss"]

    right = scoring.score_document(
        [group(EQUIPMENT, ("Main Switchboard (MSB), 600A, 480/277V, 3-phase", "1 EA"))],
        t,
        ELEC,
    )
    assert kinds(right) == ["hit"]


# ------------------------------- regressions from the first live corpus run
# Four pairs where the old set-equality gate returned 0.0 on a >=0.82 match, so
# ONE correctly-found item was scored as BOTH a miss and an extra.
LIVE_PAIRS = [
    (
        "spec detail added on the extracted side",
        "Lithonia JEBL-30000LM-GL-120V-40K-80CRI LED High-Bay Light Fixture",
        "Lithonia JEBL-30000LM-GL-120V-40K-80CRI LED Highbay Fixture, IP65, Duracoat Finish",
        True,
    ),
    (
        "numeral inside an equipment tag (ATS1)",
        "Automatic Transfer Switch ATS1",
        "Automatic Transfer Switch (ATS), 600A, 480/277V, 3-phase",
        True,
    ),
    (
        "numeral inside an equipment tag (MTS1)",
        "Manual Transfer Switch MTS1",
        "Manual Transfer Switch (MTS), 600A, 480/277V, 3-phase",
        True,
    ),
    (
        # DELIBERATELY still blocked: the extraction dropped both the size and
        # the schedule, so it did not find this item — it found something vaguer.
        "size and schedule dropped by the extraction",
        '2" Schedule 40 PVC Electrical Conduit',
        "PVC Conduit (stub up from shed)",
        False,
    ),
]


@pytest.mark.parametrize(
    "why,truth_name,extracted_name,should_match",
    LIVE_PAIRS,
    ids=[p[0] for p in LIVE_PAIRS],
)
def test_live_corpus_regressions(why, truth_name, extracted_name, should_match):
    raw = scoring.token_set_ratio(
        scoring.normalize_name(truth_name), scoring.normalize_name(extracted_name)
    )
    assert raw >= scoring.FUZZY_THRESHOLD, "fixture no longer exercises the gate"
    gated = scoring.name_similarity(truth_name, extracted_name)
    if should_match:
        assert gated >= scoring.FUZZY_THRESHOLD, why
    else:
        assert gated == 0.0, why


@pytest.mark.parametrize(
    "why,truth_name,extracted_name,should_match",
    LIVE_PAIRS,
    ids=[p[0] for p in LIVE_PAIRS],
)
def test_a_gated_match_is_one_match_not_a_miss_and_an_extra(
    why, truth_name, extracted_name, should_match
):
    """The failure mode that made the live run under-report: one item, two penalties."""
    score = scoring.score_document(
        [group(EQUIPMENT, (extracted_name, "1 EA"))],
        truth(
            item(truth_name, category=EQUIPMENT.key, quantity=1, unit="EA"),
            plan_type="electrical_plan",
        ),
        ELEC,
    )
    if should_match:
        assert kinds(score) == ["hit"]
        assert score.recall == 1.0
        assert score.precision == 1.0
        assert score.counts["miss"] == 0 and score.counts["extra"] == 0
    else:
        assert kinds(score) == ["extra", "miss"]
        assert score.recall == 0.0
        assert score.precision == 0.0


def test_same_size_different_wording_still_matches():
    score = scoring.score_document(
        [group(WATER, ('8" Gate Valves', "9 EA"))],
        truth(item('8" Gate Valve', quantity=9, unit="EA")),
        SPEC,
    )
    assert kinds(score) == ["hit"]
    assert score.recall == 1.0


# -------------------------------------------------------------- aliases
def test_alias_matches_when_the_primary_name_cannot():
    """The truth name carries a class number the extraction never says — the alias bridges it."""
    t = truth(
        item(
            '12" DI Pipe, Class 350',
            aliases=['12" ductile iron waterline', "12 inch ductile iron pipe"],
            quantity=1450,
            unit="LF",
        )
    )
    direct = scoring.score_document(
        [group(WATER, ('12" ductile iron waterline', "1,450 LF"))], t, SPEC
    )
    assert kinds(direct) == ["hit"]
    assert direct.matches[0].score == 1.0

    # …and the alias does not smuggle the size gate open.
    wrong_size = scoring.score_document(
        [group(WATER, ('8" ductile iron waterline', "1,450 LF"))], t, SPEC
    )
    assert kinds(wrong_size) == ["extra", "miss"]


# ------------------------------------------------------------- categories
def test_right_item_wrong_category_is_a_hit_with_category_ok_false():
    """A smaller failure than not finding it — and it must be visible as its own number."""
    score = scoring.score_document(
        [group(SEWER, ("Fire Hydrant Assembly", "3 EA"))],
        truth(item("Fire Hydrant Assembly", category="water", quantity=3, unit="EA")),
        SPEC,
    )
    assert kinds(score) == ["hit"]
    assert score.recall == 1.0
    match = score.matches[0]
    assert match.category_ok is False
    assert score.category_accuracy == 0.0
    # Both sides are carried, so the UI can render "sewer → water" rather than
    # just "wrong category".
    assert match.truth_category == "water"
    assert match.extracted_category == "sewer"


# ------------------------------------------------------- completeness rules
def test_precision_is_suppressed_on_partial_truth():
    """On `partial` truth an unmatched item is UNKNOWN — the label may just not cover it."""
    extracted = [group(WATER, ("Fire Hydrant Assembly", "3 EA"), ("Thrust Block", "12 EA"))]
    t_items = [item("Fire Hydrant Assembly", quantity=3, unit="EA")]

    full = scoring.score_document(extracted, truth(*t_items, completeness="full"), SPEC)
    assert kinds(full) == ["extra", "hit"]
    assert full.precision == 0.5

    partial = scoring.score_document(extracted, truth(*t_items, completeness="partial"), SPEC)
    assert kinds(partial) == ["hit", "unknown"]
    assert partial.precision is None  # not 0.0 — it is unmeasurable
    assert partial.f1 is None
    assert partial.recall == 1.0


# --------------------------------------------------------------- forbidden
def test_forbidden_hit_outranks_extra():
    """A known hallucination is a hard error, never merely an unexplained extra."""
    score = scoring.score_document(
        [group(WATER, ("Silt Fence", "—"), ("Random Widget", "1 EA"))],
        truth(
            item("Fire Hydrant Assembly", quantity=1, unit="EA"),
            forbidden=[{"name": "silt fence", "why": "legend symbol only"}],
        ),
        SPEC,
    )
    assert kinds(score) == ["extra", "forbidden", "miss"]
    assert score.hallucinations == 1
    forbidden = [m for m in score.matches if m.kind == "forbidden"][0]
    assert forbidden.extracted_name == "Silt Fence"
    # A hallucination is only actionable once the UI can say why it is wrong.
    assert forbidden.forbidden_why == "legend symbol only"
    assert forbidden.extracted_category == "water"
    # No truth counterpart exists, so nothing truth-side is invented.
    assert forbidden.truth_category is None
    assert forbidden.truth_source is None
    assert forbidden.qty_tolerance is None
    # The forbidden item is NOT also counted as an extra against precision.
    assert score.counts["extra"] == 1
    assert score.precision == 0.0


def test_forbidden_item_is_never_matched_to_truth():
    score = scoring.score_document(
        [group(WATER, ("Silt Fence", "1 EA"))],
        truth(item("Silt Fence"), forbidden=[{"name": "Silt Fence", "why": "legend only"}]),
        SPEC,
    )
    assert kinds(score) == ["forbidden", "miss"]


# ------------------------------------------------------------------ units
@pytest.mark.parametrize("unit", ["LF", "lf", "FT", "feet", "Linear Feet", "l.f."])
def test_unit_normalisation_treats_lf_ft_feet_as_one(unit):
    score = scoring.score_document(
        [group(WATER, ('8" PVC Water Main', "1450 {}".format(unit)))],
        truth(item('8" PVC Water Main', quantity=1450, unit="LF")),
        SPEC,
    )
    assert score.matches[0].unit_ok is True
    assert score.unit_accuracy == 1.0


def test_unrelated_units_are_not_equal():
    score = scoring.score_document(
        [group(WATER, ('8" PVC Water Main', "1450 EA"))],
        truth(item('8" PVC Water Main', quantity=1450, unit="LF")),
        SPEC,
    )
    assert score.matches[0].unit_ok is False
    assert score.matches[0].quantity_ok is True  # the number is right, the unit is not


def test_unit_accuracy_is_none_when_truth_states_no_unit():
    score = scoring.score_document(
        [group(WATER, ("Fire Hydrant Assembly", "3 EA"))],
        truth(item("Fire Hydrant Assembly")),
        SPEC,
    )
    assert score.matches[0].unit_ok is None
    assert score.unit_accuracy is None
    assert score.quantity_accuracy is None


# ------------------------------------------------------- greedy assignment
def test_matching_is_one_to_one_and_greedy_by_score():
    """Two similar extracted lines cannot both consume the same truth item."""
    score = scoring.score_document(
        [group(WATER, ('8" Gate Valve', "9 EA"), ('8" Gate Valves', "4 EA"))],
        truth(item('8" Gate Valve', quantity=9, unit="EA")),
        SPEC,
    )
    assert kinds(score) == ["extra", "hit"]
    hit = [m for m in score.matches if m.kind == "hit"][0]
    # The exact (1.0) pair wins the truth item; the weaker one is left over.
    assert hit.score == 1.0
    assert hit.extracted_index == 0
    assert score.counts["hit"] == 1


def test_each_truth_item_is_consumed_at_most_once():
    score = scoring.score_document(
        [group(WATER, ('8" Gate Valve', "9 EA"))],
        truth(item('8" Gate Valve', quantity=9, unit="EA"), item('8" Gate Valve', quantity=9, unit="EA")),
        SPEC,
    )
    assert kinds(score) == ["hit", "miss"]
    assert score.recall == 0.5


# ----------------------------------------------------- quantity tolerance
@pytest.mark.parametrize(
    "got,expected",
    [(1000, True), (1050, True), (950, True), (1050.01, False), (949.99, False), (1200, False)],
)
def test_quantity_tolerance_at_the_boundary(got, expected):
    score = scoring.score_document(
        [group(WATER, ('8" PVC Water Main', "{} LF".format(got)))],
        truth(item('8" PVC Water Main', quantity=1000, unit="LF", qty_tolerance=0.05)),
        SPEC,
    )
    assert score.matches[0].quantity_ok is expected
    assert score.quantity_accuracy == (1.0 if expected else 0.0)


def test_missing_quantity_fails_a_scored_quantity():
    score = scoring.score_document(
        [group(WATER, ('8" PVC Water Main', "—"))],
        truth(item('8" PVC Water Main', quantity=1000, unit="LF")),
        SPEC,
    )
    assert score.matches[0].quantity_ok is False


def test_quantity_display_parsing():
    refs = scoring.flatten_extracted(
        [group(WATER, ("A", "1,450 LF"), ("B", "—"), ("C", "12"), ("D", "3.5 CY"))], SPEC
    )
    assert [(r.quantity, r.unit) for r in refs] == [
        (1450.0, "LF"), (None, None), (12.0, None), (3.5, "CY")
    ]
    assert all(r.category == "water" for r in refs)
    assert [r.index for r in refs] == [0, 1, 2, 3]


# -------------------------------------------- context carried on a match
# The diff view has to explain a failure on its own, from the stored score.


def test_truth_source_and_tolerance_ride_along_wherever_truth_exists():
    t = truth(
        item(
            "Fire Hydrant Assembly",
            quantity=100,
            unit="EA",
            qty_tolerance=0.10,
            source="Sheet C-4, utility summary",
        ),
        item('8" Gate Valve', quantity=9, unit="EA", source="Sheet C-5, valve schedule"),
    )
    score = scoring.score_document(
        [group(WATER, ("Fire Hydrant Assembly", "72 EA"))], t, SPEC
    )
    hit = [m for m in score.matches if m.kind == "hit"][0]
    miss = [m for m in score.matches if m.kind == "miss"][0]

    # A wrong-quantity row can now show "off by -28% · tol ±10%" from the match
    # alone — enough to see whether the tolerance is the problem.
    assert hit.quantity_ok is False
    assert hit.qty_tolerance == 0.10
    assert (hit.quantity_got - hit.quantity_want) / hit.quantity_want == pytest.approx(-0.28)
    assert hit.truth_source == "Sheet C-4, utility summary"

    # …and a miss says where to go look to confirm it.
    assert miss.truth_source == "Sheet C-5, valve schedule"
    assert miss.qty_tolerance == 0.05  # the default, applied to that item
    assert miss.truth_category == "water"
    assert miss.extracted_category is None  # nothing was extracted for it


def test_an_extra_carries_only_the_extracted_side():
    score = scoring.score_document(
        [group(SEWER, ("Mystery Widget", "1 EA"))],
        truth(item("Fire Hydrant Assembly", quantity=1, unit="EA", source="Sheet C-4")),
        SPEC,
    )
    extra = [m for m in score.matches if m.kind == "extra"][0]
    assert extra.extracted_category == "sewer"
    assert extra.truth_category is None
    assert extra.truth_source is None
    assert extra.qty_tolerance is None
    assert extra.forbidden_why is None


def test_a_forbidden_entry_without_a_why_stays_none():
    score = scoring.score_document(
        [group(WATER, ("Silt Fence", "1 EA"))],
        truth(item("Fire Hydrant Assembly"), forbidden=[{"name": "silt fence"}]),
        SPEC,
    )
    forbidden = [m for m in score.matches if m.kind == "forbidden"][0]
    assert forbidden.forbidden_why is None  # not synthesised


def test_forbidden_why_is_only_set_on_forbidden_matches():
    score = scoring.score_document(
        [group(WATER, ("Fire Hydrant Assembly", "1 EA"), ("Silt Fence", "1 EA"))],
        truth(
            item("Fire Hydrant Assembly", quantity=1, unit="EA"),
            forbidden=[{"name": "silt fence", "why": "legend symbol only"}],
        ),
        SPEC,
    )
    whys = {m.kind: m.forbidden_why for m in score.matches}
    assert whys == {"hit": None, "forbidden": "legend symbol only"}


def test_extracted_category_is_none_when_the_group_maps_to_nothing():
    """Without a spec there is no label→key map, so the category is honestly unknown."""
    score = scoring.score_document(
        [{"group": "Some Group", "items": [{"n": "Fire Hydrant Assembly", "q": "1 EA"}]}],
        truth(item("Fire Hydrant Assembly", quantity=1, unit="EA")),
        None,
    )
    hit = score.matches[0]
    assert hit.kind == "hit"
    assert hit.extracted_category is None
    assert hit.truth_category == "water"
    assert hit.category_ok is False


# ------------------------------------------------------- optional items
def test_optional_items_do_not_count_against_recall():
    t = truth(
        item("Fire Hydrant Assembly", quantity=1, unit="EA"),
        item("Thrust Block", required=False),
    )
    missed_optional = scoring.score_document(
        [group(WATER, ("Fire Hydrant Assembly", "1 EA"))], t, SPEC
    )
    assert missed_optional.recall == 1.0
    assert missed_optional.optional_recall == 0.0

    found_optional = scoring.score_document(
        [group(WATER, ("Fire Hydrant Assembly", "1 EA"), ("Thrust Block", "12 EA"))], t, SPEC
    )
    assert found_optional.recall == 1.0
    assert found_optional.optional_recall == 1.0


def test_optional_recall_is_none_when_there_are_no_optional_items():
    score = scoring.score_document(
        [group(WATER, ("Fire Hydrant Assembly", "1 EA"))],
        truth(item("Fire Hydrant Assembly", quantity=1, unit="EA")),
        SPEC,
    )
    assert score.optional_recall is None


# ------------------------------------------------------------- aggregation
def test_undefined_metrics_are_none_not_zero():
    empty = scoring.score_document([], truth(completeness="partial"), SPEC)
    assert empty.recall is None  # no required truth items → unmeasurable
    assert empty.precision is None
    assert empty.f1 is None
    assert empty.category_accuracy is None
    assert empty.hallucinations == 0


def test_aggregate_macro_averages_and_keeps_undefined_none():
    full = scoring.score_document(
        [group(WATER, ("Fire Hydrant Assembly", "1 EA"))],
        truth(item("Fire Hydrant Assembly", quantity=1, unit="EA"), doc_id="a"),
        SPEC,
    )
    partial = scoring.score_document(
        [group(WATER, ("Fire Hydrant Assembly", "1 EA"), ("Extra Thing", "1 EA"))],
        truth(item("Fire Hydrant Assembly", quantity=1, unit="EA"), doc_id="b", completeness="partial"),
        SPEC,
    )
    agg = scoring.aggregate([full, partial])
    assert agg["documents"] == 2
    assert agg["recall"] == 1.0
    assert agg["precision"] == 1.0  # only the `full` doc defines precision
    assert agg["defined"]["precision"] == 1
    assert agg["counts"]["hit"] == 2
    assert agg["counts"]["unknown"] == 1


def test_aggregate_of_nothing_is_all_none():
    agg = scoring.aggregate([])
    assert agg["documents"] == 0
    for key in scoring.METRIC_KEYS:
        assert agg[key] is None


# ------------------------------------- notations that only LOOK like a size
# Found by probing the gate with names from the committed truth files: every
# pair below was a false miss (or, for 1/2" vs 2-1/2", a false HIT) before the
# pre-pass, and each is a notation that appears on nearly every building set.
NOTATION_PAIRS = [
    ("fraction is ONE dimension, not two", '1/2" Anchor Bolt', '1/2 inch anchor bolts, 7" embed', True),
    ("fraction is not satisfied by its digits", '1/2" Anchor Bolt', '2-1/2" Anchor Bolt', False),
    ("mixed number equals its decimal", '(2) 1-3/4" x 14" LVL Beam (B1)', '2-ply 1.75" x 14" LVL beam B1', True),
    ("ply count contradiction blocks", '(2) 1-3/4" x 14" LVL Beam', '(3) 1-3/4" x 14" LVL Beam', False),
    ("bar count omitted is not vaguer", '#5 Rebar, (2) top & bottom', "#5 rebar, top and bottom", True),
    ("spacing omitted is not vaguer", '9-1/2" TJI 210 Floor Joist @ 16" O.C.', '9-1/2" TJI 210 floor joists', True),
    ("spacing contradiction blocks", '#3 Rebar @ 12" O.C.', '#3 rebar @ 24" o.c.', False),
    ("NxM lumber size is two dimensions", '6" x 12" Continuous Concrete Footing', "6x12 continuous footing", True),
    ("NxM lumber size gates", "2x6 Pressure-Treated Mudsill", "2x10 pressure treated mudsill", False),
    ("AWG gauge is a code, not a fraction", "3/0 Copper Feeder", "1/0 copper feeder", False),
    ("AWG gauge agrees with itself", "3/0 Copper Feeder", "3/0 AWG copper feeder", True),
    ("voltage pair is not a fraction", "480/277V Panelboard", "480/277V panelboard, 42 circuit", True),
    ("trailing note is not a spec", "3/0 Copper Feeder (feeder mark 1, 200A/4W)", "3/0 copper feeder", True),
    ("32nds are fractions too", '23/32" OSB Subfloor, T&G', '23/32" T&G OSB subfloor', True),
    ("feet-inches is one dimension, in inches", "Pad Footing F2, 2'-0\" x 2'-0\" x 1'-6\" thick", '24" x 24" x 18" pad footing F2', True),
    ("feet-inches still gates", "Continuous Footing, 1'-3\" wide", '12" wide continuous footing', False),
    ("thousands separator is not two numbers", "3,000 psi Concrete — Footings", "3000 psi concrete footings", True),
    ("thousands separator still gates", "3,000 psi Concrete — Footings", "2,500 psi concrete footings", False),
    ("alpha-led catalogue number is a code", "R-3067-7004-V Casting", "R-3067-7004-V casting, frame and grate", True),
    ("alpha-led catalogue numbers contradict", "R-3067-7004-V Casting", "R-1550 casting", False),
]


@pytest.mark.parametrize(
    "why,truth_name,extracted_name,should_match",
    NOTATION_PAIRS,
    ids=[p[0] for p in NOTATION_PAIRS],
)
def test_size_notations_are_read_as_estimators_write_them(why, truth_name, extracted_name, should_match):
    gated = scoring.name_similarity(truth_name, extracted_name)
    if should_match:
        assert gated >= scoring.FUZZY_THRESHOLD, why
    else:
        assert gated == 0.0, why


def test_fractions_and_products_become_dimensions():
    assert scoring.dimensional_numbers('1/2" Anchor Bolt') == {"0.5": 1}
    assert scoring.dimensional_numbers('1-3/4" x 14" LVL') == {"1.75": 1, "14": 1}
    assert scoring.dimensional_numbers("2x6 Stud") == {"2": 1, "6": 1}
    assert scoring.dimensional_numbers("4x4x8 Post") == {"4": 2, "8": 1}
    # Counts and spacing are recorded, keyed, so they can only contradict.
    assert scoring.code_values("(2) 2x10 Header") == {"count": {"2"}}
    assert scoring.code_values('2x6 Studs @ 16" O.C.') == {"oc": {"16"}}
    assert scoring.code_values("3/0 Copper") == {"/0": {"3"}}
    assert scoring.dimensional_numbers("3/0 Copper") == {}
    assert scoring.dimensional_numbers("Footing 1'-3\" wide") == {"15": 1}
    assert scoring.dimensional_numbers("3,000 psi concrete") == {"3000": 1}
    assert scoring.code_values("R-3067-7004-V Casting") == {"r": {"3067", "7004"}}
    assert scoring.dimensional_numbers("R-3067-7004-V Casting") == {}


# ------------------------------------------------ usable recall + scale errors
def test_usable_recall_counts_only_lines_an_rfq_could_use():
    t = truth(
        item('8" PVC Water Main', quantity=1000, unit="LF"),       # found, right
        item('6" Gate Valve', quantity=4, unit="EA"),             # found, qty wrong
        item("Fire Hydrant", quantity=3, unit="EA"),              # found, unit wrong
        item("Tapping Sleeve"),                                   # found, nothing stated → usable
        item('12" DI Pipe', quantity=200, unit="LF"),             # missed
    )
    score = scoring.score_document(
        [group(
            WATER,
            ('8" PVC Water Main', "1000 LF"),
            ('6" Gate Valve', "8 EA"),
            ("Fire Hydrant", "3 LF"),
            ("Tapping Sleeve", "—"),
        )],
        t,
        SPEC,
    )
    assert score.recall == 4 / 5
    assert score.usable_recall == 2 / 5
    assert score.counts["quantity_wrong"] == 1


def test_usable_recall_is_none_without_required_items():
    score = scoring.score_document(
        [group(WATER, ("Fire Hydrant", "3 EA"))],
        truth(item("Fire Hydrant", quantity=3, unit="EA", required=False)),
        SPEC,
    )
    assert score.usable_recall is None
    assert score.optional_recall == 1.0


@pytest.mark.parametrize(
    "ratio,expected",
    [
        (None, None), (1.0, None), (1.04, None), (1.5, None),
        (8.0, 8), (7.5, 8), (0.125, -8), (0.13, -8), (3.0, 3), (2.0, 2), (0.5, -2),
        (0.9, None), (1.2, None), (30.0, 30), (1 / 37.0, -37), (100.0, None),
    ],
)
def test_scale_factor_reads_integer_multiples(ratio, expected):
    assert scoring.scale_factor(ratio) == expected


def test_a_never_scaled_typical_unit_count_is_a_scale_error():
    """The 54-61 failure mode: 15 lights per unit reported for an 8-unit building."""
    lighting = ELEC.category("lighting")
    t = truth(
        item("Ceiling Light Fixture", category="lighting", quantity=116, unit="EA", qty_tolerance=0.15),
        item("Duplex Receptacle", category="devices", quantity=240, unit="EA", qty_tolerance=0.2),
        plan_type="electrical_plan",
    )
    score = scoring.score_document(
        [
            group(lighting, ("Ceiling Light Fixture", "15 EA")),
            group(ELEC.category("devices"), ("Duplex Receptacle", "200 EA")),
        ],
        t,
        ELEC,
    )
    by_name = {m.truth_name: m for m in score.matches}
    assert by_name["Ceiling Light Fixture"].quantity_ok is False
    assert abs(by_name["Ceiling Light Fixture"].quantity_ratio - 15 / 116) < 1e-9
    assert scoring.scale_factor(by_name["Ceiling Light Fixture"].quantity_ratio) == -8
    # 200 vs 240 is a misread, not a scale error.
    assert by_name["Duplex Receptacle"].quantity_ok is True
    assert score.counts["scale_errors"] == 1
    assert score.counts["quantity_wrong"] == 1
    assert score.usable_recall == 0.5
    assert score.to_dict()["usable_recall"] == 0.5
    assert score.to_dict()["matches"][0]["quantity_ratio"] is not None


def test_quantity_ratio_is_none_where_it_cannot_be_computed():
    score = scoring.score_document(
        [group(WATER, ("Fire Hydrant", "3 EA"), ("Tapping Sleeve", "—"))],
        truth(item("Fire Hydrant"), item("Tapping Sleeve", quantity=2, unit="EA")),
        SPEC,
    )
    for m in score.matches:
        assert m.quantity_ratio is None


def test_aggregate_carries_usable_recall_and_scale_errors():
    a = scoring.score_document(
        [group(WATER, ('8" PVC Water Main', "8000 LF"))],
        truth(item('8" PVC Water Main', quantity=1000, unit="LF")),
        SPEC,
    )
    b = scoring.score_document(
        [group(WATER, ('8" PVC Water Main', "1000 LF"))],
        truth(item('8" PVC Water Main', quantity=1000, unit="LF")),
        SPEC,
    )
    agg = scoring.aggregate([a, b])
    assert agg["usable_recall"] == 0.5
    assert agg["counts"]["scale_errors"] == 1
    assert agg["defined"]["usable_recall"] == 2


def test_negative_control_scores_every_extracted_line_as_an_extra():
    """An empty `full` truth: the document is not a plan set, so anything found is invented."""
    control = truth()  # full, no items
    clean = scoring.score_document([], control, SPEC)
    assert clean.precision is None and clean.recall is None  # nothing to divide
    assert clean.counts["extra"] == 0
    hallucinated = scoring.score_document(
        [group(WATER, ('8" PVC Water Main', "500 LF"), ("Fire Hydrant", "2 EA"))], control, SPEC
    )
    assert kinds(hallucinated) == ["extra", "extra"]
    assert hallucinated.precision == 0.0
    assert hallucinated.recall is None
    assert hallucinated.counts["extra"] == 2


# --------------------------------- artefacts the first live baseline exposed
def test_an_exact_name_outranks_a_subset_alias_on_another_line():
    """`hydrant` is a subset of `6" PVC Hydrant Lead` too; the exact line must win."""
    t = truth(
        item("Fire Hydrant Assembly", quantity=4, unit="EA", aliases=["fire hydrant", "hydrant"]),
        item('6" PVC Water Line (hydrant lead)', quantity=None, unit="LF", aliases=['6" PVC pipe']),
    )
    score = scoring.score_document(
        [group(WATER, ('6" PVC Hydrant Lead', "74.4 LF"), ("Fire Hydrant Assembly", "4 EA"))], t, SPEC
    )
    by_truth = {m.truth_name: m for m in score.matches if m.truth_name}
    assert by_truth["Fire Hydrant Assembly"].extracted_name == "Fire Hydrant Assembly"
    assert by_truth["Fire Hydrant Assembly"].quantity_ok is True


def test_a_bare_word_alias_does_not_match_a_longer_line():
    assert scoring.name_similarity("hydrant", '6" PVC Hydrant Lead') == 0.0
    assert scoring.name_similarity("hydrant", "Fire Hydrant") >= scoring.FUZZY_THRESHOLD
    assert scoring.name_similarity("hydrant", "hydrant") == 1.0


def test_fuzzy_never_scores_as_high_as_exact():
    assert scoring.name_similarity('12" DI Pipe', '12" DI Pipe, Class 350') <= scoring.FUZZY_CEILING
    assert scoring.name_similarity('12" DI Pipe', '12" DI Pipe') == 1.0


def test_ties_go_to_the_matching_category():
    """Two 4' manholes, one per discipline: each truth item gets its own."""
    storm = SPEC.category("storm")
    t = truth(
        item("Storm Sewer Manhole", category="storm", quantity=7, unit="EA", aliases=["standard 4' manhole"]),
        item("Sanitary Sewer Manhole", category="sewer", quantity=11, unit="EA", aliases=["standard 4' manhole"]),
    )
    score = scoring.score_document(
        [
            group(SEWER, ("Standard 4' Diameter Manhole, Water-Tight", "11 EA")),
            group(storm, ("Standard 4' Diameter Storm Manhole", "7 EA")),
        ],
        t,
        SPEC,
    )
    by_truth = {m.truth_name: m for m in score.matches}
    assert by_truth["Storm Sewer Manhole"].quantity_got == 7 and by_truth["Storm Sewer Manhole"].category_ok
    assert by_truth["Sanitary Sewer Manhole"].quantity_got == 11 and by_truth["Sanitary Sewer Manhole"].category_ok
    assert score.quantity_accuracy == 1.0


@pytest.mark.parametrize(
    "truth_name,extracted_name,should_match",
    [
        ('8" PVC SDR 26 Sanitary Sewer', '8" PVC SDR-26 Gravity Sewer Main', True),
        ('8" PVC SDR 26 Sanitary Sewer', '8" PVC SDR-35 Sanitary Sewer', False),
        ("Schedule 40 PVC Conduit", "SCH-40 PVC conduit", True),
        ("Schedule 40 PVC Conduit", "Sch. 80 PVC conduit", False),
        ('1/2" Anchor Bolt @ 6\' O.C.', '1/2" Diameter Anchor Bolts at 6\'-0" O.C. max', True),
        ('1/2" Anchor Bolt @ 6\' O.C.', '1/2" anchor bolts @ 48" o.c.', False),
        ('1/2" Anchor Bolt @ 6\' O.C.', '1/2" anchor bolts @ 72" o.c.', True),
    ],
)
def test_spec_words_and_spacing_are_read_however_punctuated(truth_name, extracted_name, should_match):
    gated = scoring.name_similarity(truth_name, extracted_name)
    assert (gated >= scoring.FUZZY_THRESHOLD) == should_match, (truth_name, extracted_name, gated)


def test_normalised_names_fold_notation_the_same_way_on_both_sides():
    assert scoring.normalize_name('1/2" Anchor Bolt') == "0.5 inch anchor bolt"
    assert scoring.normalize_name("Pad Footing 2'-0\" x 2'-0\"") == "pad footing 24 inch x 24 inch"
    assert scoring.normalize_name("3,000 psi concrete") == "3000 psi concrete"
    assert scoring.normalize_name("2x6 studs") == "2 x 6 stud"
    assert scoring.normalize_name("SDR-26 pipe") == "sdr 26 pipe"
