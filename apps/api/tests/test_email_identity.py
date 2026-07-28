"""Outbound email identity: one workspace From, the buyer on Cc.

Everything Proq sends leaves the connected Gmail mailbox
(PROCUREAI_GMAIL_SENDER_ADDRESS). A user's own address is carried as the From
display name and as a Cc — never as the From address itself, and never as a
Reply-To (supplier replies have to come back to the mailbox quote ingest reads).

Provider credentials are force-blanked in conftest before app import, so nothing
here can reach Gmail; the workspace address is monkeypatched per test.
"""
import base64
from email import message_from_bytes
from email.header import decode_header, make_header
from email.utils import parseaddr
from types import SimpleNamespace

import pytest

from app.config import settings
from app.services.rfq import sender as rfq_sender
from tests.conftest import generate_rfq, make_confirmed_bom, run_supplier_search

WORKSPACE = "bids@workspace.example.com"


@pytest.fixture()
def workspace_address(monkeypatch):
    """A configured PROCUREAI_GMAIL_SENDER_ADDRESS (still no OAuth creds → mock)."""
    monkeypatch.setattr(settings, "gmail_sender_address", WORKSPACE)
    assert not rfq_sender.is_configured(), "OAuth creds must stay blank in tests"
    return WORKSPACE


def _user(name="Jane Doe", company="Acme Construction", cc_email=None):
    return SimpleNamespace(name=name, company=company, cc_email=cc_email)


def _decode(raw: str):
    """The MIME message back out of the base64url blob _build_mime produces."""
    return message_from_bytes(base64.urlsafe_b64decode(raw))


def _label(header: str) -> str:
    """The display name of a From header, undoing any RFC2047 encoding."""
    return str(make_header(decode_header(parseaddr(header)[0])))


# --------------------------------------------------------------- From header
def test_from_is_the_workspace_address_whatever_the_user_set(workspace_address):
    for cc in (None, "", "jane@herowncompany.com", WORKSPACE):
        header = rfq_sender.from_header(_user(cc_email=cc))
        assert parseaddr(header)[1] == WORKSPACE


def test_from_carries_the_buyers_name_and_company(workspace_address):
    header = rfq_sender.from_header(_user())
    assert parseaddr(header)[1] == WORKSPACE
    # The em dash is non-ASCII, so formataddr RFC2047-encodes the label; it
    # decodes back to the readable name in every mail client.
    assert _label(header) == "Jane Doe — Acme Construction"
    # …and the display twin is the same identity, already readable.
    assert rfq_sender.from_display(_user()) == (
        f"Jane Doe — Acme Construction <{WORKSPACE}>"
    )
    assert rfq_sender.from_display(_user(name="", company="")) == WORKSPACE


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
    header = rfq_sender.from_header(user)
    assert parseaddr(header)[1] == WORKSPACE
    assert _label(header) == expected_name
    # No orphaned separator or empty label left behind.
    assert "—" not in header and '""' not in header


def test_from_display_name_with_a_comma_stays_one_address(workspace_address):
    """formataddr must quote the label, or the comma would split the header."""
    header = rfq_sender.from_header(_user(name="Doe, Jane", company=""))
    assert header.startswith('"Doe, Jane"')
    assert parseaddr(header)[1] == WORKSPACE


def test_from_falls_back_to_the_bare_address_with_no_identity(workspace_address):
    assert rfq_sender.from_header(None) == WORKSPACE
    assert rfq_sender.from_header(_user(name="", company="")) == WORKSPACE


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


def test_built_mime_sets_cc_and_never_reply_to(workspace_address):
    from_addr = rfq_sender.from_header(_user())
    msg = _decode(
        rfq_sender._build_mime(
            "supplier@x.com", "RFQ", "body", from_addr, cc="jane@acme.com"
        )
    )
    assert msg["To"] == "supplier@x.com"
    assert parseaddr(msg["From"])[1] == WORKSPACE
    assert msg["Cc"] == "jane@acme.com"
    # Supplier replies must land in the workspace mailbox — see sender.py.
    assert msg["Reply-To"] is None


def test_built_mime_omits_cc_when_unset_or_duplicate(workspace_address):
    plain = _decode(
        rfq_sender._build_mime("supplier@x.com", "RFQ", "body", WORKSPACE)
    )
    assert plain["Cc"] is None
    dupe = _decode(
        rfq_sender._build_mime(
            "supplier@x.com", "RFQ", "body", WORKSPACE, cc="supplier@x.com"
        )
    )
    assert dupe["Cc"] is None


def test_mock_sender_logs_the_cc(workspace_address, caplog):
    with caplog.at_level("INFO", logger="procureai.rfq.sender"):
        rfq_sender.MockSender().send(
            "supplier@x.com", "RFQ", "body", from_addr=WORKSPACE, cc="jane@acme.com"
        )
    assert "cc=jane@acme.com" in caplog.text


# ------------------------------------------------------------- config surface
def test_email_config_flags_the_placeholder_address(monkeypatch):
    monkeypatch.setattr(settings, "gmail_sender_address", "")
    cfg = rfq_sender.email_config()
    assert cfg["configured"] is False and cfg["mocked"] is True
    assert cfg["senderAddressSet"] is False
    assert cfg["fromAddress"] == rfq_sender.UNCONFIGURED_SENDER_ADDRESS


def test_email_config_reports_a_configured_address(workspace_address):
    cfg = rfq_sender.email_config()
    assert cfg["senderAddressSet"] is True
    assert cfg["fromAddress"] == WORKSPACE
    assert cfg["mocked"] is True  # address alone isn't enough — OAuth creds too


# --------------------------------------------------------- end-to-end RFQ send
class _Recorder:
    mocked = True

    def __init__(self):
        self.sent = []

    def send(self, to, subject, body, *, from_addr, cc=None, thread_id=None,
             in_reply_to=None):
        self.sent.append({"to": to, "from_addr": from_addr, "cc": cc})
        return rfq_sender.SentMessage(message_id=f"rec-{len(self.sent)}", thread_id="t")


def _send_rfq(client, headers, pid, recorder, monkeypatch):
    bom_id = make_confirmed_bom(client, headers, pid)
    sids = run_supplier_search(client, headers, pid, bom_id)
    rfq = generate_rfq(client, headers, pid, bom_id, sids[:2])
    monkeypatch.setattr(rfq_sender, "get_sender", lambda: recorder)
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
