"""Outbound email identity: the organization's agent inbox is the From, the
buyer is on Cc.

Everything Proq sends for an organization leaves that org's AgentMail inbox.
A user's own address is carried as the From display name and as a Cc, never
as the From address itself, and never as a Reply-To (supplier replies have to
come back to the inbox the webhook reads).

Provider credentials are force-blanked in conftest before app import, so
nothing here can reach AgentMail; the inbox address is passed explicitly.
"""
from email.header import decode_header, make_header
from email.utils import parseaddr
from types import SimpleNamespace

import pytest

from app.services.rfq import sender as rfq_sender
from tests.conftest import generate_rfq, make_confirmed_bom, run_supplier_search

WORKSPACE = "acme@proq.tryproq.dev"


@pytest.fixture()
def workspace_address():
    """An organization whose agent inbox exists (still no API key → mock)."""
    assert not rfq_sender.is_configured(), "the API key must stay blank in tests"
    return WORKSPACE


def _user(name="Jane Doe", company="Acme Construction", cc_email=None):
    return SimpleNamespace(name=name, company=company, cc_email=cc_email)


def _label(header: str) -> str:
    """The display name of a From header, undoing any RFC2047 encoding."""
    return str(make_header(decode_header(parseaddr(header)[0])))


# --------------------------------------------------------------- From header
def test_from_is_the_workspace_address_whatever_the_user_set(workspace_address):
    for cc in (None, "", "jane@herowncompany.com", WORKSPACE):
        header = rfq_sender.from_header(_user(cc_email=cc), address=WORKSPACE)
        assert parseaddr(header)[1] == WORKSPACE


def test_from_carries_the_buyers_name_and_company(workspace_address):
    header = rfq_sender.from_header(_user(), address=WORKSPACE)
    assert parseaddr(header)[1] == WORKSPACE
    assert _label(header) == "Jane Doe: Acme Construction"
    # ...and the display twin is the same identity, already readable.
    assert rfq_sender.from_display(_user(), address=WORKSPACE) == (
        f"Jane Doe: Acme Construction <{WORKSPACE}>"
    )
    assert rfq_sender.from_display(_user(name="", company=""), address=WORKSPACE) == WORKSPACE


def test_non_ascii_names_are_rfc2047_encoded_on_the_wire():
    header = rfq_sender.from_header(_user(name="José Núñez", company="Acme"), address=WORKSPACE)
    assert "=?utf-8?" in header and parseaddr(header)[1] == WORKSPACE
    assert _label(header) == "José Núñez: Acme"


@pytest.mark.parametrize(
    "user,expected_name",
    [
        (_user(company=""), "Jane Doe"),
        (_user(name=""), "Acme Construction"),
        (_user(name="", company=""), ""),
        (_user(name="  ", company="  "), ""),
    ],
)
def test_from_display_name_degrades_without_dangling_separators(
    workspace_address, user, expected_name
):
    header = rfq_sender.from_header(user, address=WORKSPACE)
    assert parseaddr(header)[1] == WORKSPACE
    assert _label(header) == expected_name
    # No orphaned separator or empty label left behind.
    assert ":" not in _label(header) and '""' not in header


def test_from_display_name_with_a_comma_stays_one_address(workspace_address):
    """formataddr must quote the label, or the comma would split the header."""
    header = rfq_sender.from_header(_user(name="Doe, Jane", company=""), address=WORKSPACE)
    assert header.startswith('"Doe, Jane"')
    assert parseaddr(header)[1] == WORKSPACE


def test_from_falls_back_to_the_bare_address_with_no_identity(workspace_address):
    assert rfq_sender.from_header(None, address=WORKSPACE) == WORKSPACE
    assert rfq_sender.from_header(_user(name="", company=""), address=WORKSPACE) == WORKSPACE
    # Before the org's inbox exists the placeholder stands in (never delivered).
    assert rfq_sender.from_header(None) == rfq_sender.UNCONFIGURED_SENDER_ADDRESS


# ---------------------------------------------------------------- Cc handling
@pytest.mark.parametrize(
    "cc,to,from_addr,expected",
    [
        ("jane@acme.com", "supplier@x.com", WORKSPACE, "jane@acme.com"),
        (None, "supplier@x.com", WORKSPACE, None),
        ("", "supplier@x.com", WORKSPACE, None),
        ("   ", "supplier@x.com", WORKSPACE, None),
        # Already on the message → no duplicate copy.
        ("supplier@x.com", "supplier@x.com", WORKSPACE, None),
        ("SUPPLIER@X.COM", "supplier@x.com", WORKSPACE, None),
        (WORKSPACE, "supplier@x.com", WORKSPACE, None),
        # …including when From carries a display name.
        (WORKSPACE, "supplier@x.com", f'"Jane" <{WORKSPACE}>', None),
    ],
)
def test_resolve_cc_drops_duplicates_and_blanks(cc, to, from_addr, expected):
    assert rfq_sender.resolve_cc(cc, to, from_addr) == expected


def test_mock_sender_logs_the_cc(workspace_address, caplog):
    with caplog.at_level("INFO", logger="procureai.rfq.sender"):
        rfq_sender.MockSender().send(
            "supplier@x.com", "RFQ", "body", from_addr=WORKSPACE, cc="jane@acme.com"
        )
    assert "cc=jane@acme.com" in caplog.text


# ------------------------------------------------------------- config surface
def test_email_config_has_no_inbox_before_the_first_send(auth):
    client, headers = auth
    from app.db import SessionLocal

    me = client.get("/api/auth/me", headers=headers).json()
    db = SessionLocal()
    try:
        cfg = rfq_sender.email_config(db, me["organizationId"])
    finally:
        db.close()
    assert cfg["configured"] is False and cfg["mocked"] is True
    assert cfg["inboxAddress"] is None


def test_email_config_reports_the_orgs_inbox_once_it_exists(auth):
    client, headers = auth
    from app.db import SessionLocal
    from app.models.organization import Organization

    me = client.get("/api/auth/me", headers=headers).json()
    db = SessionLocal()
    try:
        org = db.get(Organization, me["organizationId"])
        org.agentmail_inbox_id = WORKSPACE
        db.commit()
        cfg = rfq_sender.email_config(db, me["organizationId"])
        assert rfq_sender.sender_address(db, me["organizationId"]) == WORKSPACE
    finally:
        db.close()
    assert cfg["inboxAddress"] == WORKSPACE
    assert cfg["mocked"] is True  # the address alone isn't enough: the key too
    cfg = client.get("/api/auth/email-config", headers=headers).json()
    assert cfg["inboxAddress"] == WORKSPACE and cfg["fromHeader"] == f"PM <{WORKSPACE}>"


# --------------------------------------------------------- end-to-end RFQ send
class _Recorder:
    mocked = True

    def __init__(self):
        self.sent = []

    address = WORKSPACE

    def send(self, to, subject, body, *, from_addr, cc=None, thread_id=None,
             in_reply_to=None, attachments=None, reply_to=None):
        self.sent.append({"to": to, "from_addr": from_addr, "cc": cc})
        return rfq_sender.SentMessage(message_id=f"rec-{len(self.sent)}", thread_id="t")


def _send_rfq(client, headers, pid, recorder, monkeypatch):
    bom_id = make_confirmed_bom(client, headers, pid)
    sids = run_supplier_search(client, headers, pid, bom_id)
    rfq = generate_rfq(client, headers, pid, bom_id, sids[:2])
    monkeypatch.setattr(rfq_sender, "get_sender", lambda *a, **k: recorder)
    r = client.post(f"/api/projects/{pid}/rfqs/{rfq['id']}/send", headers=headers)
    assert r.status_code == 200, r.text


def test_rfq_send_uses_workspace_from_and_ccs_the_user(project, monkeypatch,
                                                       workspace_address):
    client, headers, pid = project
    client.patch("/api/auth/me", headers=headers, json={"ccEmail": "pm@ownfirm.com"})
    recorder = _Recorder()
    _send_rfq(client, headers, pid, recorder, monkeypatch)

    assert recorder.sent
    for m in recorder.sent:
        assert parseaddr(m["from_addr"])[1] == WORKSPACE  # never pm@ownfirm.com
        assert m["cc"] == "pm@ownfirm.com"


def test_rfq_send_without_a_cc_address(project, monkeypatch, workspace_address):
    client, headers, pid = project
    recorder = _Recorder()
    _send_rfq(client, headers, pid, recorder, monkeypatch)

    assert recorder.sent
    for m in recorder.sent:
        assert parseaddr(m["from_addr"])[1] == WORKSPACE
        assert m["cc"] is None
