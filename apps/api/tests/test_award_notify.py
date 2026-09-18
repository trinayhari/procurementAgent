"""Award-notification emails: winners get a PO for only their lines, losers get a
decline note, and each threads into the supplier's RFQ conversation."""
from email.utils import parseaddr
from types import SimpleNamespace

from app.services.rfq import award_notify
from app.services.rfq.sender import UNCONFIGURED_SENDER_ADDRESS, SentMessage


class RecordingSender:
    """Stand-in EmailSender that captures every send (no network)."""

    mocked = True

    def __init__(self):
        self.sent = []

    def send(self, to, subject, body, *, from_addr, cc=None, thread_id=None,
             in_reply_to=None):
        self.sent.append(dict(to=to, subject=subject, body=body, from_addr=from_addr,
                              cc=cc, thread_id=thread_id, in_reply_to=in_reply_to))
        return SentMessage(message_id=f"rec-{len(self.sent)}", thread_id=thread_id or "t")


def _line(name, unit, ext, qty="1 EA", lead=None):
    return {"name": name, "qty": qty, "unitPrice": unit, "extended": ext, "leadDays": lead}


def _quote(sid, name, email, freight, lines, rfq_id="rfq1"):
    return {"supplierId": sid, "supplierName": name, "supplierEmail": email,
            "freight": freight, "rfqId": rfq_id, "lineItems": lines}


ALPHA = _quote("a", "Alpha Supply", "alpha@x.com", 100.0,
               [_line("Pipe", 10, 1000, "100 LF", 10), _line("Valve", 55, 600)])
BETA = _quote("b", "Beta Supply", "beta@x.com", 80.0,
              [_line("Pipe", 12, 1200), _line("Valve", 45, 450, "10 EA", 8)])
GAMMA = _quote("g", "Gamma Co", "gamma@x.com", 90.0,
               [_line("Pipe", 13, 1300), _line("Valve", 50, 500)])

RFQ = {
    "subject": "RFQ: Water Utilities — Test Project",
    "recipients": [
        {"email": "alpha@x.com", "threadId": "thread-a", "sentMessageId": "msg-a"},
        {"email": "beta@x.com", "threadId": "thread-b", "sentMessageId": "msg-b"},
        {"email": "gamma@x.com", "threadId": "thread-g", "sentMessageId": "msg-g"},
    ],
}

# Split award: Pipe → Alpha, Valve → Beta. Gamma quoted but wasn't selected.
SUMMARY = {
    "selections": {"Pipe": "a", "Valve": "b"},
    "supplierIds": {"a", "b"},
    "suppliers": ["Alpha Supply", "Beta Supply"],
    "material": 1450.0, "freight": 180.0, "total": 1630.0, "poCount": 2,
}

BUYER = SimpleNamespace(name="Jordan Mills", company="Meridian Civil", cc_email=None)
# Same buyer, now asking to be copied on the mail they trigger.
BUYER_CC = SimpleNamespace(name="Jordan Mills", company="Meridian Civil",
                           cc_email="jordan@meridiancivil.com")


def _patch(monkeypatch, quotes, rfq=RFQ):
    monkeypatch.setattr(award_notify.quotes_repo, "list_quotes", lambda db, org_id, pid, pkg: quotes)
    monkeypatch.setattr(award_notify.rfqs_repo, "get_rfq", lambda db, org_id, rid: rfq)


def test_split_award_emails_each_winner_only_their_lines(monkeypatch):
    _patch(monkeypatch, [ALPHA, BETA, GAMMA])
    sender = RecordingSender()

    res = award_notify.notify_award(
        None, org_id="org", project_id="p", package="water", package_label="Water Utilities",
        summary=SUMMARY, buyer=BUYER, sender=sender,
    )

    assert {w["supplier"] for w in res["notified"]} == {"Alpha Supply", "Beta Supply"}
    assert [d["supplier"] for d in res["declined"]] == ["Gamma Co"]
    assert res["failed"] == []
    assert len(sender.sent) == 3

    by_to = {m["to"]: m for m in sender.sent}

    # Alpha won only Pipe: PO lists Pipe, not Valve; total = 1000 + 100 freight.
    alpha = by_to["alpha@x.com"]
    assert alpha["subject"] == "Re: RFQ: Water Utilities — Test Project"
    assert alpha["thread_id"] == "thread-a"        # threaded into Alpha's RFQ
    assert alpha["in_reply_to"] is None            # mock sender → no header fetch
    # From is the workspace mailbox (Gmail unconfigured in tests → the labelled
    # placeholder), never the buyer's own address.
    assert parseaddr(alpha["from_addr"])[1] == UNCONFIGURED_SENDER_ADDRESS
    assert alpha["cc"] is None                     # this buyer set no Cc address
    assert "Pipe" in alpha["body"] and "Valve" not in alpha["body"]
    assert "$1,000.00" in alpha["body"]            # materials (Alpha's Pipe)
    assert "$1,100.00" in alpha["body"]            # total incl. freight
    assert "10-day lead" in alpha["body"]
    assert "Meridian Civil" in alpha["body"]       # signature

    # Beta won only Valve: total = 450 + 80.
    beta = by_to["beta@x.com"]
    assert beta["thread_id"] == "thread-b"
    assert "Valve" in beta["body"] and "Pipe" not in beta["body"]
    assert "$530.00" in beta["body"]

    # Gamma: decline note, still threaded.
    gamma = by_to["gamma@x.com"]
    assert gamma["thread_id"] == "thread-g"
    assert "another supplier" in gamma["body"]
    assert "Pipe" not in gamma["body"] and "$" not in gamma["body"]


def test_buyer_is_cced_on_every_award_email(monkeypatch):
    """The buyer's own address rides along as a Cc — it is never the From."""
    _patch(monkeypatch, [ALPHA, BETA, GAMMA])
    sender = RecordingSender()

    award_notify.notify_award(
        None, org_id="org", project_id="p", package="water", package_label="Water Utilities",
        summary=SUMMARY, buyer=BUYER_CC, sender=sender,
    )

    assert len(sender.sent) == 3
    for m in sender.sent:
        assert m["cc"] == "jordan@meridiancivil.com"
        assert parseaddr(m["from_addr"])[1] == UNCONFIGURED_SENDER_ADDRESS


def test_declined_can_be_suppressed(monkeypatch):
    _patch(monkeypatch, [ALPHA, BETA, GAMMA])
    sender = RecordingSender()
    res = award_notify.notify_award(
        None, org_id="org", project_id="p", package="water", package_label="Water Utilities",
        summary=SUMMARY, buyer=BUYER, sender=sender, notify_declined=False,
    )
    assert res["declined"] == []
    assert {m["to"] for m in sender.sent} == {"alpha@x.com", "beta@x.com"}


def test_winner_without_email_is_recorded_failed(monkeypatch):
    no_email = _quote("a", "Alpha Supply", "", 100.0, [_line("Pipe", 10, 1000)])
    _patch(monkeypatch, [no_email, BETA, GAMMA])
    sender = RecordingSender()
    res = award_notify.notify_award(
        None, org_id="org", project_id="p", package="water", package_label="Water Utilities",
        summary=SUMMARY, buyer=BUYER, sender=sender,
    )
    assert [f["supplier"] for f in res["failed"]] == ["Alpha Supply"]
    assert "alpha@x.com" not in {m["to"] for m in sender.sent}
    assert any(w["supplier"] == "Beta Supply" for w in res["notified"])


def test_no_thread_when_recipient_missing(monkeypatch):
    # RFQ exists but this supplier isn't among its recipients → send un-threaded,
    # using the package subject rather than "Re:".
    rfq_no_alpha = {"subject": "RFQ: Water", "recipients": [
        {"email": "beta@x.com", "threadId": "thread-b", "sentMessageId": "msg-b"},
    ]}
    _patch(monkeypatch, [ALPHA, BETA], rfq=rfq_no_alpha)
    sender = RecordingSender()
    award_notify.notify_award(
        None, org_id="org", project_id="p", package="water", package_label="Water Utilities",
        summary={"selections": {"Pipe": "a", "Valve": "b"}, "supplierIds": {"a", "b"},
                 "suppliers": ["Alpha Supply", "Beta Supply"], "total": 1630.0, "poCount": 2},
        buyer=BUYER, sender=sender, notify_declined=False,
    )
    alpha = next(m for m in sender.sent if m["to"] == "alpha@x.com")
    assert alpha["thread_id"] is None
    assert alpha["subject"] == "Purchase order — Water Utilities"
