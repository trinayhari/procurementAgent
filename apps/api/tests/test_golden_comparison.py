"""Golden cases for the quote comparison + recommendation engine.

`build_comparison` ranks a package's quotes on a 60/30/10 cost/lead/risk blend
and names one supplier. These cases pin the outcomes a buyer would sanity-check
by hand — cheapest wins when leads are close, a much faster quote can beat a
slightly cheaper one, an incomplete quote is never recommended over a complete
one — so a weight or scoring tweak that flips an award fails a NAMED case here.

The repo is monkeypatched with canned quotes (the shape `quotes_repo.list_quotes`
returns), so no database or provider is involved.
"""
import pytest

from app.services.quotes import comparison


def _quote(name, total, lead, material=None, freight=None, email="x@example.com"):
    return {
        "supplierId": name.lower(),
        "supplierName": name,
        "supplierEmail": email,
        "materialCost": material if material is not None else (total - (freight or 0.0) if total is not None else None),
        "freight": freight,
        "total": total,
        "leadDays": lead,
        "lineItems": [],
    }


def _run(monkeypatch, quotes):
    monkeypatch.setattr(comparison.quotes_repo, "list_quotes", lambda db, org, pid, pkg: quotes)
    return comparison.build_comparison(None, "org", "proj", "water", "Water Utilities")


GOLDEN = [
    (
        "cheapest wins when lead times are close",
        [_quote("Alpha", 100_000, 14), _quote("Beta", 104_000, 12), _quote("Gamma", 110_000, 10)],
        "Alpha",
        ["Lowest total bid"],
        "$10,000",
    ),
    (
        "25 days faster beats 1% cheaper (deltas are measured, not min-maxed)",
        # Min-max normalisation used to make the cheapest quote cost 0.0 and the
        # dearest 1.0 whatever the gap, so with two quotes cost's 0.6 weight
        # ALWAYS beat lead's 0.3 + risk's 0.1 — a $1 saving outranked a month
        # of lead time. Penalties are now relative (% over the cheapest, days
        # behind the fastest), so a 1% premium is a small cost and 25 days a
        # large one. (Savings is measured off the recommended quote: Beta IS
        # the highest bid here, hence $0.)
        [_quote("Alpha", 99_000, 35), _quote("Beta", 100_000, 10)],
        "Beta",
        ["Fastest lead time at 10 days", "Lowest delivery risk (score 90)"],
        "$0",
    ),
    (
        "a clearly cheaper quote still wins over a slightly faster one",
        # 8% dearer for 3 days sooner is not worth it.
        [_quote("Alpha", 100_000, 17), _quote("Beta", 108_000, 14)],
        "Alpha",
        ["Lowest total bid"],
        "$8,000",
    ),
    (
        "a trivial lead-time edge does not overturn a real price gap",
        # Beta is 1 day faster (under the 2-day floor) and 3% dearer.
        [_quote("Alpha", 100_000, 15), _quote("Beta", 103_000, 14)],
        "Alpha",
        ["Lowest total bid"],
        "$3,000",
    ),
    (
        "a quote with no total is never recommended over a complete one",
        [_quote("Alpha", None, 5), _quote("Beta", 120_000, 20)],
        "Beta",
        ["Lowest total bid", "Lowest delivery risk (score 80)"],
        "—",
    ),
    (
        "identical totals fall to the faster, lower-risk supplier",
        [_quote("Alpha", 80_000, 30), _quote("Beta", 80_000, 12)],
        "Beta",
        ["Lowest total bid", "Fastest lead time at 12 days", "Lowest delivery risk (score 88)"],
        "$0",
    ),
]


@pytest.mark.parametrize("why,quotes,winner,reasons,savings", GOLDEN, ids=[g[0] for g in GOLDEN])
def test_recommendation_golden(monkeypatch, why, quotes, winner, reasons, savings):
    out = _run(monkeypatch, quotes)
    assert out is not None
    assert out["recommendation"] == winner, why
    assert out["reasons"] == reasons, why
    assert out["savings"] == savings, why
    flagged = [s["name"] for s in out["suppliers"] if s["rec"]]
    assert flagged == [winner]


def test_best_markers_point_at_the_minimum_of_each_row(monkeypatch):
    out = _run(monkeypatch, [
        _quote("Alpha", 100_000, 14, material=95_000, freight=5_000),
        _quote("Beta", 98_000, 21, material=97_000, freight=1_000),
        _quote("Gamma", 105_000, 7, material=104_500, freight=500),
    ])
    rows = {r["label"]: r for r in out["rows"]}
    assert rows["Material Cost"]["best"] == 0  # Alpha 95k
    assert rows["Freight"]["best"] == 2  # Gamma 500
    assert rows["Total Cost"]["best"] == 1  # Beta 98k
    assert rows["Lead Time"]["best"] == 2  # Gamma 7 days
    assert rows["Total Cost"]["vals"] == ["$100,000", "$98,000", "$105,000"]
    assert rows["Lead Time"]["vals"] == ["14 days", "21 days", "7 days"]


def test_risk_score_bands_are_stable():
    """Risk is what breaks ties; its bands must not drift silently."""
    assert comparison._risk_score(_quote("A", 1.0, 5)) == 95
    assert comparison._risk_score(_quote("A", 1.0, 40)) == 60
    assert comparison._risk_score(_quote("A", 1.0, 90)) == 60  # lead penalty caps at 40
    assert comparison._risk_score(_quote("A", None, None)) == 55  # no lead, no total
    assert comparison._risk_score(_quote("A", 1.0, 5, email="")) == 90
    assert comparison._risk_label(95) == "95 · Low"
    assert comparison._risk_label(70) == "70 · Med"
    assert comparison._risk_label(60) == "60 · High"


def test_single_quote_has_no_savings_claim(monkeypatch):
    out = _run(monkeypatch, [_quote("Alpha", 100_000, 14)])
    assert out["recommendation"] == "Alpha"
    assert out["savings"] == "—"
    assert out["savingsNote"] == "Awaiting more quotes to compute savings"


def test_recommendation_is_scale_independent(monkeypatch):
    """The same relative trade-off must resolve the same way at $10K and $10M:
    the score reads a price premium as a fraction of the cheapest total, not as
    a position on a min-max range."""
    for scale in (1, 1_000, 1_000_000):
        out = _run(monkeypatch, [
            _quote("Alpha", 99 * scale, 35), _quote("Beta", 100 * scale, 10),
        ])
        assert out["recommendation"] == "Beta", scale
        out = _run(monkeypatch, [
            _quote("Alpha", 90 * scale, 35), _quote("Beta", 100 * scale, 10),
        ])
        assert out["recommendation"] == "Alpha", scale  # 10% is worth 25 days


def test_one_dollar_cheaper_does_not_beat_a_month_faster(monkeypatch):
    out = _run(monkeypatch, [_quote("Alpha", 99_999, 40), _quote("Beta", 100_000, 10)])
    assert out["recommendation"] == "Beta"
    # …but with equal lead times the $1 still breaks the tie the cheap way.
    out = _run(monkeypatch, [_quote("Alpha", 99_999, 10), _quote("Beta", 100_000, 10)])
    assert out["recommendation"] == "Alpha"


def test_penalty_floors_and_missing_values():
    pen = comparison._relative_penalties([100.0, 100.4, 110.0, None], 0.10, 0.005, relative=True)
    assert pen[0] == 0.0 and pen[1] == 0.0  # within the 0.5% floor
    assert abs(pen[2] - 0.95) < 1e-9  # (10% − 0.5%) / 10%
    assert pen[3] == pen[2] + 1.0  # missing is always worse than every present value
    lead = comparison._relative_penalties([10.0, 12.0, 40.0], 30.0, 2.0, relative=False)
    assert lead == [0.0, 0.0, 28.0 / 30.0]
    assert comparison._relative_penalties([None, None], 1.0, 0.0, relative=False) == [0.0, 0.0]
