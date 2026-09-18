"""Round-2 reliability regressions (BUG-38 … BUG-43 + residuals)."""
import threading
import time

from app.services.rfq import sender as rfq_sender
from tests.conftest import generate_rfq, make_confirmed_bom, run_supplier_search


def _flow_to_quotes(client, headers, pid):
    bom_id = make_confirmed_bom(client, headers, pid)
    sids = run_supplier_search(client, headers, pid, bom_id)
    rfq = generate_rfq(client, headers, pid, bom_id, sids[:3])
    client.post(f"/api/projects/{pid}/rfqs/{rfq['id']}/send", headers=headers)
    client.post(f"/api/projects/{pid}/quotes/ingest", headers=headers)
    return bom_id


# ------------------------------------------------------------------ BUG-38
def test_concurrent_awards_produce_exactly_one_decision_and_one_notification_batch(project, monkeypatch):
    """A triple-clicked 'Confirm award' fired three overlapping POST /award
    requests; each passed the check-then-insert and issued POs + emailed every
    supplier. The award now runs under a per-package lock: one wins, the
    others answer 409 at once."""
    client, headers, pid = project
    bom_id = _flow_to_quotes(client, headers, pid)

    sent = []
    gate = threading.Event()

    class SlowSender:
        mocked = True

        def send(self, to, subject, body, **kw):
            gate.wait(5)  # hold the winner inside the notification batch
            sent.append(to)
            return rfq_sender.SentMessage(message_id=f"m-{len(sent)}", thread_id="t")

    monkeypatch.setattr(rfq_sender, "get_sender", lambda: SlowSender())
    url = f"/api/projects/{pid}/packages/{bom_id}/award"
    results = []

    def go():
        results.append(client.post(url, headers=headers, json={"selections": {}, "strategy": "mix"}))

    threads = [threading.Thread(target=go) for _ in range(3)]
    threads[0].start()
    time.sleep(0.3)  # the first request is inside the sender, holding the lock
    for t in threads[1:]:
        t.start()
    for t in threads[1:]:
        t.join(5)
    gate.set()
    threads[0].join(10)

    codes = sorted(r.status_code for r in results)
    assert codes == [200, 409, 409], [(r.status_code, r.text) for r in results]
    losers = [r.json()["detail"] for r in results if r.status_code == 409]
    assert all("being awarded right now" in d for d in losers)
    decisions = client.get(f"/api/projects/{pid}/purchase-decisions", headers=headers).json()
    assert len(decisions) == 1
    batch = len(sent)
    assert batch >= 1  # one notification batch, every recipient exactly once
    assert len(set(sent)) == batch
    audit = client.get("/api/audit", headers=headers).json()
    assert sum(1 for a in audit if a["action"] == "package.awarded") == 1
    assert sum(1 for a in audit if a["action"] == "package.award_notified") == 1


# ------------------------------------------------------------------ BUG-30
def test_invite_without_an_email_provider_returns_the_accept_link_and_can_be_resent(auth):
    """In mock mode the UI said 'Invitation sent' while nothing was delivered
    and the token lived only in the database. Now the response says it was
    not emailed and carries the accept link; resend hands it back again."""
    client, headers = auth
    r = client.post("/api/team/invites", headers=headers, json={"email": "newbie@example.com"})
    assert r.status_code == 201, r.text
    inv = r.json()
    assert inv["emailed"] is False
    assert inv["acceptUrl"] and "/#/invite/" in inv["acceptUrl"]
    token = inv["acceptUrl"].rsplit("/", 1)[-1]
    # The link works for the invitee.
    assert client.get(f"/api/invite/{token}").status_code == 200
    # The roster carries the link too, and resend returns it again.
    team = client.get("/api/team", headers=headers).json()
    assert team["invites"][0]["acceptUrl"] == inv["acceptUrl"]
    r = client.post(f"/api/team/invites/{inv['id']}/resend", headers=headers)
    assert r.status_code == 200 and r.json()["acceptUrl"] == inv["acceptUrl"]
    assert client.post("/api/team/invites/nope/resend", headers=headers).status_code == 404


def test_invite_link_stays_private_when_real_email_is_configured(auth, monkeypatch):
    """The real-email path is unchanged: the token is never exposed."""
    client, headers = auth
    from app.api.routes import team as team_routes
    from app.services.rfq import sender as rfq_sender

    sent = []

    class RealishSender:
        mocked = False

        def send(self, to, subject, body, **kw):
            sent.append(to)
            return rfq_sender.SentMessage(message_id="m", thread_id="t")

    monkeypatch.setattr(team_routes.rfq_sender, "get_sender", lambda: RealishSender())
    monkeypatch.setattr(team_routes.rfq_sender, "is_configured", lambda: True)
    r = client.post("/api/team/invites", headers=headers, json={"email": "real@example.com"})
    assert r.status_code == 201
    assert r.json()["emailed"] is True and r.json()["acceptUrl"] is None
    assert sent == ["real@example.com"]
    assert client.get("/api/team", headers=headers).json()["invites"][0]["acceptUrl"] is None


# --------------------------------------------------------- BUG-27 residual
def test_project_value_must_look_like_an_amount(auth):
    client, headers = auth
    r = client.post("/api/projects", headers=headers, json={"name": "V1", "value": "abc"})
    assert r.status_code == 422
    assert "must be an amount" in r.text
    for ok in ("$4.2M", "450,000", "1.5 b", "", "12000.50", "$3k"):
        r = client.post("/api/projects", headers=headers, json={"name": f"V {ok}", "value": ok})
        assert r.status_code == 201, (ok, r.text)


# ------------------------------------------------------ activity meta text
def test_activity_meta_is_not_duplicated_and_pluralises_pages(project, monkeypatch):
    client, headers, pid = project
    from app.api.routes import documents as documents_routes
    from tests.test_reliability import _MINI_PDF, _upload

    monkeypatch.setattr(documents_routes, "_run_pipeline", lambda *a, **k: None)
    _upload(client, headers, "one.pdf", _MINI_PDF, plan_type="other")
    feed = client.get("/api/dashboard", headers=headers).json()["activity"]
    metas = [a["meta"] for a in feed]
    assert "Test Project" in metas  # 'Project created' — not 'Test Project · Test Project'
    assert not any(" · Test Project" in m and m.startswith("Test Project") for m in metas)
    assert any(m.endswith("· 1 page") for m in metas), metas
