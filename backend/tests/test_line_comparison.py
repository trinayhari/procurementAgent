"""Award optimizer coverage for quotes that contain unpriced ("quote pending") lines.

A supplier reply legitimately has lines with no price yet (e.g. a "TBD"-quantity
item). Those must not zero out every award strategy: the optimizer awards over the
lines at least one supplier priced, treats universally-unpriced lines as
informational, and still enforces per-supplier gaps on the priceable lines.

Tested at the service layer with canned quotes (monkeypatching the repo) so the
scenario is explicit — mock-ingested quotes are always fully priced.
"""
import pytest

from app.services.quotes import line_comparison as lc


def _line(name, unit, ext, lead):
    return {"name": name, "qty": "1 EA", "unitPrice": unit, "extended": ext, "leadDays": lead}


def _quote(sid, name, freight, dist, lines):
    return {
        "supplierId": sid,
        "supplierName": name,
        "freight": freight,
        "distanceMiles": dist,
        "leadDays": max((l["leadDays"] for l in lines if l["leadDays"] is not None), default=None),
        "total": None,
        "lineItems": lines,
    }


PENDING = _line("Special (TBD)", None, None, None)  # no supplier can price this


def _patch_quotes(monkeypatch, quotes):
    monkeypatch.setattr(lc.quotes_repo, "list_quotes", lambda db, pid, pkg: quotes)


def test_universally_unpriced_line_does_not_block_strategies(monkeypatch):
    quotes = [
        _quote("a", "Alpha", 100.0, 20.0, [_line("Pipe", 10, 1000, 10), _line("Valve", 50, 500, 20), dict(PENDING)]),
        _quote("b", "Beta", 80.0, 40.0, [_line("Pipe", 12, 1200, 5), _line("Valve", 45, 450, 8), dict(PENDING)]),
    ]
    _patch_quotes(monkeypatch, quotes)

    res = lc.build_line_comparison(db=None, project_id="p", package="water", package_label="Water")
    assert res is not None
    keys = {o["key"] for o in res["options"]}
    assert {"mix", "fastest", "single"} <= keys, keys
    assert all(o["total"] > 0 for o in res["options"])

    # The pending line is surfaced but never awarded.
    rows = {l["name"]: l for l in res["lines"]}
    assert rows["Special (TBD)"]["pending"] is True
    assert rows["Pipe"]["pending"] is False and rows["Valve"]["pending"] is False
    for o in res["options"]:
        assert "Special (TBD)" not in o["selections"]

    # Freight-aware: a single supplier (Alpha) beats splitting here, so the pending
    # line's absence doesn't distort the numbers.
    single = next(o for o in res["options"] if o["key"] == "single")
    assert single["total"] == 1600.0 and single["material"] == 1500.0  # Alpha: 1000+500 + 100
    mix = next(o for o in res["options"] if o["key"] == "mix")
    assert mix["total"] == 1600.0 and mix["suppliersUsed"] == 1
    fastest = next(o for o in res["options"] if o["key"] == "fastest")
    assert fastest["total"] == 1730.0 and fastest["leadDays"] == 8  # both from Beta


def test_priceable_line_only_one_supplier_offers_still_awards(monkeypatch):
    # 'Fitting' is priced by Beta only → it IS priceable, so completeness requires
    # it and Alpha (which lacks it) can't win 'single'; Beta can. 'Special' is
    # unpriced by everyone and stays out of the math.
    quotes = [
        _quote("a", "Alpha", 100.0, 20.0, [_line("Pipe", 10, 1000, 10), _line("Valve", 50, 500, 20), dict(PENDING)]),
        _quote("b", "Beta", 80.0, 40.0, [
            _line("Pipe", 12, 1200, 5), _line("Valve", 45, 450, 8), _line("Fitting", 20, 200, 3), dict(PENDING),
        ]),
    ]
    _patch_quotes(monkeypatch, quotes)

    res = lc.build_line_comparison(db=None, project_id="p", package="water", package_label="Water")
    keys = {o["key"] for o in res["options"]}
    assert {"mix", "fastest", "single"} <= keys, keys

    rows = {l["name"]: l for l in res["lines"]}
    assert rows["Fitting"]["pending"] is False and rows["Special (TBD)"]["pending"] is True

    # single must be Beta (covers all 3 priceable lines); Alpha is disqualified.
    single = next(o for o in res["options"] if o["key"] == "single")
    assert set(single["selections"].values()) == {"b"}
    assert set(single["selections"]) == {"Pipe", "Valve", "Fitting"}
    assert single["total"] == 1930.0  # 1200+450+200 + 80

    # mix splits Pipe→Alpha, Valve/Fitting→Beta (material 1650 + freight 180).
    mix = next(o for o in res["options"] if o["key"] == "mix")
    assert mix["material"] == 1650.0 and mix["suppliersUsed"] == 2 and mix["total"] == 1830.0


def test_compute_award_ignores_pending_lines(monkeypatch):
    quotes = [
        _quote("a", "Alpha", 100.0, 20.0, [_line("Pipe", 10, 1000, 10), _line("Valve", 50, 500, 20), dict(PENDING)]),
        _quote("b", "Beta", 80.0, 40.0, [_line("Pipe", 12, 1200, 5), _line("Valve", 45, 450, 8), dict(PENDING)]),
    ]
    _patch_quotes(monkeypatch, quotes)

    # Empty selection → cheapest per priceable line (Pipe→Alpha 1000, Valve→Beta 450).
    award = lc.compute_award(db=None, project_id="p", package="water", selections={})
    assert award is not None
    assert "Special (TBD)" not in award["selections"]
    assert award["material"] == 1450.0
    assert award["total"] == 1630.0  # 1450 + freight(100+80)
    assert award["poCount"] == 2


def test_all_lines_pending_yields_no_award(monkeypatch):
    quotes = [
        _quote("a", "Alpha", 100.0, 20.0, [dict(PENDING)]),
        _quote("b", "Beta", 80.0, 40.0, [dict(PENDING)]),
    ]
    _patch_quotes(monkeypatch, quotes)

    res = lc.build_line_comparison(db=None, project_id="p", package="water", package_label="Water")
    assert res is not None
    assert res["options"] == []  # nothing priceable → no strategies, but grid still returned
    assert res["lines"][0]["pending"] is True
    assert lc.compute_award(db=None, project_id="p", package="water", selections={}) is None
