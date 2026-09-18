"""Golden fixtures for the quote-ingest path: supplier reply → ParsedQuote → finalized figures.

Every case in tests/golden/quotes/*.json is a supplier reply as Gmail delivers it
(or a structured-output response as the model returns it) with the numbers the
pipeline MUST derive. Nothing here calls a model: the provider creds are blanked
by conftest, so `parse_quote` exercises the regex fallback, and `finalize_quote`
is pure arithmetic. A change in either path that moves a dollar shows up here as
a failing named fixture rather than as a wrong award weeks later.
"""
import glob
import json
import os

import pytest

from app.services.quotes import gmail_reader, ingest, parser
from app.services.quotes.models import ParsedQuote

GOLDEN_DIR = os.path.join(os.path.dirname(__file__), "golden", "quotes")


def _fixtures(key):
    out = []
    for path in sorted(glob.glob(os.path.join(GOLDEN_DIR, "*.json"))):
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if key in data:
            out.append(pytest.param(data, id=os.path.basename(path)[:-5]))
    return out


def _check(parsed: ParsedQuote, expect: dict) -> None:
    for field_name, want in expect.items():
        got = getattr(parsed, field_name)
        assert got == want, "{}: got {!r}, want {!r}".format(field_name, got, want)


@pytest.mark.parametrize("case", _fixtures("expect_regex"))
def test_regex_fallback_reads_the_reply(case):
    assert not parser.is_configured(), "golden tests must run on the deterministic path"
    parsed = parser.parse_quote(case["text"])
    _check(parsed, case["expect_regex"])
    if "expect_regex_lines" in case:
        got = [{"name": li.name, "quantity": li.quantity, "unit_price": li.unit_price}
               for li in parsed.line_items]
        assert got == case["expect_regex_lines"]
    if "expect_regex_finalized" in case:
        ingest.fill_quantities_from_rfq(parsed, case.get("rfq_lines"))
        ingest.finalize_quote(parsed)
        assert parsed.material_cost == case["expect_regex_finalized"]["material_cost"]
        assert parsed.total == case["expect_regex_finalized"]["total"]


@pytest.mark.parametrize("case", _fixtures("expect_finalized"))
def test_finalize_derives_what_the_supplier_left_out(case):
    parsed = ParsedQuote(**case["llm_shaped"])
    ingest.finalize_quote(parsed)
    want = case["expect_finalized"]
    assert parsed.material_cost == want["material_cost"]
    assert parsed.total == want["total"]
    assert parsed.lead_days == want["lead_days"]
    assert [li.extended for li in parsed.line_items] == want["extended"]
    if "notes_contains" in want:
        assert want["notes_contains"] in (parsed.notes or "")
    if "notes_is" in want:
        assert parsed.notes == want["notes_is"]


def test_finalize_never_overrides_a_supplier_stated_header():
    """Supplier-stated subtotal/total win over our arithmetic, even when they disagree."""
    parsed = ParsedQuote(
        is_quote=True, material_cost=1000.0, freight=50.0, total=1100.0, lead_days=7,
        line_items=[{"name": "Pipe", "quantity": "10 LF", "unit_price": 90.0}],
    )
    ingest.finalize_quote(parsed)
    assert parsed.line_items[0].extended == 900.0  # per-line math is ours
    assert parsed.material_cost == 1000.0  # header figures are theirs
    assert parsed.total == 1100.0
    assert parsed.notes is None  # nothing was computed at the header level


@pytest.mark.parametrize("case", _fixtures("expect_regex_stripped"))
def test_a_reply_on_top_of_a_quoted_chain_is_read_from_the_new_text_only(case):
    """A revised quote quoting the earlier one: the parser must see the NEW figures.

    `gmail_reader._strip_quoted` drops the quoted chain; this pins that the strip
    is what makes the difference, so nobody wires the parser to unstripped text.
    """
    stripped = gmail_reader._strip_quoted(case["text"])
    _check(parser.parse_quote(stripped), case["expect_regex_stripped"])
    # And the trap, recorded: unstripped text reads the OLD total.
    _check(parser.parse_quote(case["text"]), case["expect_regex_unstripped"])


def test_inbound_message_text_is_stripped_of_the_quoted_chain(monkeypatch):
    """`fetch_replies` is the only producer of parser input; its text must be stripped."""
    import base64

    reply = (
        "Grand total: $47,500.00 delivered\nLead time: 2 weeks\n\n"
        "On Tue, Sep 9, 2026 at 3:12 PM Sam <sam@example-supply.com> wrote:\n"
        "> Grand total: $52,000.00 delivered\n"
    )
    payload = {
        "mimeType": "text/plain",
        "headers": [
            {"name": "From", "value": "Sam <sam@example-supply.com>"},
            {"name": "Subject", "value": "Re: RFQ"},
        ],
        "body": {"data": base64.urlsafe_b64encode(reply.encode()).decode()},
    }

    class _Exec:
        def __init__(self, value):
            self._value = value

        def execute(self):
            return self._value

    class _Messages:
        def list(self, **kw):
            return _Exec({"messages": [{"id": "m1"}]})

        def get(self, **kw):
            return _Exec({"payload": payload, "snippet": ""})

    class _Users:
        def messages(self):
            return _Messages()

    class _Service:
        def users(self):
            return _Users()

    monkeypatch.setattr(gmail_reader, "_service", lambda: _Service())
    msgs = gmail_reader.fetch_replies(["sam@example-supply.com"])
    assert len(msgs) == 1
    assert "$52,000" not in msgs[0].combined_text
    parsed = parser.parse_quote(msgs[0].combined_text)
    assert parsed.total == 47500.0
