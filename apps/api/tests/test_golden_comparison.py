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
        "KNOWN WEAKNESS: 1% cheaper beats 25 days faster (min-max is scale-blind)",
        # Min-max normalisation makes the cheapest quote cost 0.0 and the dearest
        # 1.0 whatever the gap, so with two quotes cost's 0.6 weight ALWAYS beats
        # lead's 0.3 + risk's 0.1 — a $1 saving outranks a month of lead time.
        # Pinned so a fix (e.g. normalise on relative spread) is a deliberate,
        # visible change; see the eval report's recommendations.
        [_quote("Alpha", 99_000, 35), _quote("Beta", 100_000, 10)],
        "Alpha",
        ["Lowest total bid"],
        "$1,000",
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
