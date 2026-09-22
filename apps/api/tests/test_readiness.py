"""Award readiness: when the agent recommends, what it recommends, and that
the award card goes out once per quote set."""
from datetime import datetime, timedelta, timezone

from app.config import settings
from app.db import SessionLocal
from app.models.approval_token import ApprovalToken
from app.models.package_recommendation import PackageRecommendation
from app.models.rfq import Rfq
from app.repositories import quotes as quotes_repo
from app.services import notify
from app.services.notify import kinds
from app.services.rfq import readiness
from tests.conftest import generate_rfq, make_confirmed_bom, run_supplier_search


def _org(client, headers):
    return client.get("/api/auth/me", headers=headers).json()["organizationId"]


def _sent_rfq(client, headers, pid, n=3):
    bom_id = make_confirmed_bom(client, headers, pid)
    sids = run_supplier_search(client, headers, pid, bom_id)
    rfq = generate_rfq(client, headers, pid, bom_id, sids[:n])
    r = client.post(f"/api/projects/{pid}/rfqs/{rfq['id']}/send", headers=headers)
    assert r.status_code == 200, r.text
    return bom_id, r.json()


def _quote(db, org_id, pid, bom_id, rfq, recipient, price, lead=10):
    return quotes_repo.create_quote(
        db, org_id, project_id=pid, package=bom_id, package_label="Hydrants Package",
        rfq_id=rfq["id"], supplier_id=recipient.get("supplierId"), supplier_name=recipient["name"],
        supplier_email=recipient["email"], material_cost=price, freight=50.0, total=price + 50.0,
        lead_days=lead, line_items=[
            {"name": "Fire hydrant", "qty": "5 EA", "unitPrice": price / 10, "extended": price / 2, "leadDays": lead},
            {"name": "8-inch gate valve", "qty": "9 EA", "unitPrice": price / 18, "extended": price / 2, "leadDays": lead},
        ],
    )


class _Memo:
    name = "memo"

    def __init__(self):
        self.seen = []

    def notify(self, db, notice):
        self.seen.append(notice)


def test_not_ready_until_everyone_replied_or_the_window_lapsed(project):
    client, headers, pid = project
    org_id = _org(client, headers)
    bom_id, rfq = _sent_rfq(client, headers, pid)
    r1, r2, r3 = rfq["recipients"]
    with SessionLocal() as db:
        assert readiness.evaluate(db, org_id, pid, bom_id) is None  # no quotes at all
        _quote(db, org_id, pid, bom_id, rfq, r1, 1000.0)
        _quote(db, org_id, pid, bom_id, rfq, r2, 1200.0)
        assert readiness.evaluate(db, org_id, pid, bom_id) is None  # one still out
        # Backdate the send past the second follow-up window: stop waiting.
        row = db.get(Rfq, rfq["id"])
        row.sent_at = datetime.now(timezone.utc) - timedelta(hours=settings.followup_second_delay_hours + 1)
        db.commit()
        rec = readiness.evaluate(db, org_id, pid, bom_id)
    assert rec is not None
    assert rec.quotes_received == 2 and rec.recipients_total == 3
    assert rec.package_label == "Hydrants Package"
    assert rec.total > 0 and set(rec.award) == {"selections", "strategy", "supersede"}


def test_ready_when_every_recipient_quoted_and_recommends_the_cheapest_basket(project):
    client, headers, pid = project
    org_id = _org(client, headers)
    bom_id, rfq = _sent_rfq(client, headers, pid, n=2)
    r1, r2 = rfq["recipients"]
    with SessionLocal() as db:
        _quote(db, org_id, pid, bom_id, rfq, r1, 1000.0, lead=14)
        _quote(db, org_id, pid, bom_id, rfq, r2, 1300.0, lead=16)
        rec = readiness.evaluate(db, org_id, pid, bom_id)
    assert rec is not None
    # Both lines are cheaper at r1 and its freight is the same: single winner.
    assert [s["supplierName"] for s in rec.suppliers] == [r1["name"]]
    assert not rec.split and rec.savings == 0
    assert rec.total == 1050.0 and rec.material == 1000.0 and rec.freight == 50.0
    assert rec.lead_days == 14
    assert set(rec.award["selections"].values()) == {r1["supplierId"]}
    lines = readiness.card_lines(rec)
    assert lines[0] == "Quotes leveled to the line: 2 of 2 suppliers"
    assert lines[1].startswith("Single supplier recommended")
    assert lines[2] == "Lead time 14d"


def test_split_recommendation_reports_savings_vs_best_single_bid(project):
    client, headers, pid = project
    org_id = _org(client, headers)
    bom_id, rfq = _sent_rfq(client, headers, pid, n=2)
    r1, r2 = rfq["recipients"]
    with SessionLocal() as db:
        # r1 cheap on hydrants, r2 cheap on valves; freight $50 each is well
        # under the per-line gap, so the mix beats either single bid.
        quotes_repo.create_quote(
            db, org_id, project_id=pid, package=bom_id, package_label="Hydrants Package",
            rfq_id=rfq["id"], supplier_id=r1["supplierId"], supplier_name=r1["name"],
            supplier_email=r1["email"], material_cost=1500.0, freight=50.0, total=1550.0, lead_days=14,
            line_items=[{"name": "Fire hydrant", "qty": "5 EA", "unitPrice": 100.0, "extended": 500.0, "leadDays": 14},
                        {"name": "8-inch gate valve", "qty": "9 EA", "unitPrice": 111.0, "extended": 1000.0, "leadDays": 14}],
        )
        quotes_repo.create_quote(
            db, org_id, project_id=pid, package=bom_id, package_label="Hydrants Package",
            rfq_id=rfq["id"], supplier_id=r2["supplierId"], supplier_name=r2["name"],
            supplier_email=r2["email"], material_cost=1500.0, freight=50.0, total=1550.0, lead_days=16,
            line_items=[{"name": "Fire hydrant", "qty": "5 EA", "unitPrice": 200.0, "extended": 1000.0, "leadDays": 16},
                        {"name": "8-inch gate valve", "qty": "9 EA", "unitPrice": 55.0, "extended": 500.0, "leadDays": 16}],
        )
        rec = readiness.evaluate(db, org_id, pid, bom_id)
    assert rec is not None and rec.split
    assert rec.total == 1100.0 and rec.single_total == 1550.0 and rec.savings == 450.0
    assert sorted(s["total"] for s in rec.suppliers) == [550.0, 550.0]
    lines = readiness.card_lines(rec)
    assert lines[1] == "Split award recommended: $450 under best single bid, freight priced in"
    # One lead per winner, in supplier-name order (the mock names vary).
    assert sorted(lines[2].removeprefix("Lead time ").split(" / ")) == ["14d", "16d"]


def test_announce_emits_once_per_quote_set_and_mints_a_token(project, monkeypatch):
    client, headers, pid = project
    org_id = _org(client, headers)
    bom_id, rfq = _sent_rfq(client, headers, pid, n=2)
    r1, r2 = rfq["recipients"]
    memo = _Memo()
    notify.register(memo)
    try:
        with SessionLocal() as db:
            _quote(db, org_id, pid, bom_id, rfq, r1, 1000.0)
            _quote(db, org_id, pid, bom_id, rfq, r2, 1200.0)
            first = readiness.announce(db, org_id, pid, bom_id)
            again = readiness.announce(db, org_id, pid, bom_id)  # same quotes: silent
        assert first and first["token"] and again is None
        ready = [n for n in memo.seen if n.kind == kinds.AWARD_READY]
        assert len(ready) == 1
        n = ready[0]
        assert n.title == "Test Project: Hydrants Package award ready"
        assert n.lines[0] == "Quotes leveled to the line: 2 of 2 suppliers"
        approve, compare = n.actions
        assert approve.label == "Approve award" and approve.style == "primary"
        assert approve.url.endswith(f"/#/approve/{first['token']}")
        assert compare.url.endswith(f"/#/project/{pid}/quotes/compare/{bom_id}")
        with SessionLocal() as db:
            tok = db.query(ApprovalToken).filter(ApprovalToken.token == first["token"]).one()
            assert tok.organization_id == org_id and tok.package == bom_id
            assert tok.award_request()["selections"]
            live = db.query(PackageRecommendation).filter(PackageRecommendation.superseded_at.is_(None)).all()
            assert len(live) == 1 and live[0].token_id == tok.id
            # A new (revised) quote changes the set: a fresh card and token go out,
            # the earlier recommendation is superseded.
            _quote(db, org_id, pid, bom_id, rfq, r2, 900.0)
            second = readiness.announce(db, org_id, pid, bom_id)
            assert second and second["token"] != first["token"]
            live = db.query(PackageRecommendation).filter(PackageRecommendation.superseded_at.is_(None)).all()
            assert len(live) == 1 and live[0].token_id == second["id"]
        assert sum(1 for n in memo.seen if n.kind == kinds.AWARD_READY) == 2
    finally:
        notify._NOTIFIERS[:] = [n for n in notify._NOTIFIERS if n.name != "memo"]


def test_ingest_announces_readiness_end_to_end(project):
    """The mock ingest answers for every recipient, so one pass makes the
    package ready: a token exists and the feed shows the award card."""
    client, headers, pid = project
    bom_id = make_confirmed_bom(client, headers, pid)
    sids = run_supplier_search(client, headers, pid, bom_id)
    rfq = generate_rfq(client, headers, pid, bom_id, sids[:3])
    client.post(f"/api/projects/{pid}/rfqs/{rfq['id']}/send", headers=headers)
    client.post(f"/api/projects/{pid}/quotes/ingest", headers=headers)
    client.post(f"/api/projects/{pid}/quotes/ingest", headers=headers)  # second pass: no new card
    with SessionLocal() as db:
        tokens = db.query(ApprovalToken).all()
    assert len(tokens) == 1
    feed = client.get(f"/api/projects/{pid}", headers=headers).json()["activity"]
    titles = [e["title"] for e in feed]
    assert titles.count("Test Project: Hydrants Package award ready") == 1
    assert "Test Project: 3 of 3 suppliers replied for Hydrants Package" in titles
    assert "Test Project: RFQ sent for Hydrants Package" in titles


def test_announce_skips_an_awarded_package(project):
    client, headers, pid = project
    org_id = _org(client, headers)
    bom_id = make_confirmed_bom(client, headers, pid)
    sids = run_supplier_search(client, headers, pid, bom_id)
    rfq = generate_rfq(client, headers, pid, bom_id, sids[:2])
    client.post(f"/api/projects/{pid}/rfqs/{rfq['id']}/send", headers=headers)
    client.post(f"/api/projects/{pid}/quotes/ingest", headers=headers)
    assert client.post(f"/api/projects/{pid}/packages/{bom_id}/award", headers=headers,
                       json={"selections": {}}).status_code == 200
    with SessionLocal() as db:
        assert readiness.announce(db, org_id, pid, bom_id) is None
        # The award settled the standing recommendation.
        assert db.query(PackageRecommendation).filter(PackageRecommendation.superseded_at.is_(None)).count() == 0
