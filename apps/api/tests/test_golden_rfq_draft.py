"""Golden snapshot of the RFQ / bid-request drafts on the deterministic (template) path.

These are the exact emails suppliers receive when no model is configured — and
the opening paragraph is shared with the LLM path, so it is what the model is
asked to keep. A wording change is fine, but it should be a deliberate one:
update the snapshot in the same commit.
"""
from app.services.rfq.generator import generate_rfq_draft, generate_sub_rfq_draft


class Buyer:
    name = "Jane Doe"
    company = "Acme Construction"


PROJECT = {"name": "North BB Creek Townhouses", "loc": "Taylor, TX"}
ITEMS = [
    {"n": '8" PVC C900 Water Main', "q": "1,450 LF"},
    {"n": "Fire Hydrant Assembly", "q": "4 EA"},
    {"n": "Tapping Sleeve and Valve"},  # no quantity → no dash
]
SUPPLIERS = [
    {"id": "s1", "name": "Core & Main", "email": "quotes@coreandmain.example"},
    {"id": "s2", "name": "No Email Supply", "email": ""},
    {"id": "s3", "name": "Ferguson", "email": "bids@ferguson.example"},
]

EXPECTED_BODY = (
    "My name is Jane Doe with Acme Construction. We are looking for a supplier of "
    "water utilities for our North BB Creek Townhouses project in Taylor, TX. "
    "Please provide unit pricing, current lead times, freight charges, available "
    "substitution options, and quote validity for the following items:\n\n"
    '- 8" PVC C900 Water Main — 1,450 LF\n'
    "- Fire Hydrant Assembly — 4 EA\n"
    "- Tapping Sleeve and Valve"
)


def test_material_rfq_draft_snapshot():
    draft = generate_rfq_draft(PROJECT, "Water Utilities", ITEMS, SUPPLIERS, buyer=Buyer())
    assert draft.subject == "RFQ: Water Utilities — North BB Creek Townhouses"
    assert draft.body.startswith(EXPECTED_BODY), draft.body
    # Only suppliers with an email are recipients, in the order given.
    assert [r["email"] for r in draft.recipients] == [
        "quotes@coreandmain.example",
        "bids@ferguson.example",
    ]
    assert draft.line_items == ITEMS


def test_recipients_are_capped_at_ten():
    many = [{"id": f"s{i}", "name": f"S{i}", "email": f"s{i}@example.com"} for i in range(14)]
    draft = generate_rfq_draft(PROJECT, "Water Utilities", ITEMS, many)
    assert len(draft.recipients) == 10
    assert draft.recipients[0]["supplierId"] == "s0"


def test_acronym_package_labels_keep_their_case():
    draft = generate_rfq_draft(PROJECT, "PVC Pipe", ITEMS, SUPPLIERS)
    assert "a supplier of PVC pipe for our" in draft.body


def test_sub_bid_request_snapshot():
    draft = generate_sub_rfq_draft(
        PROJECT,
        "Electrical",
        "Rough-in and trim for 8 townhouse units per sheets A9-A11; panels by others.",
        SUPPLIERS,
        buyer=Buyer(),
    )
    assert draft.subject == "Bid Request: Electrical — North BB Creek Townhouses"
    assert draft.body.startswith("My name is Jane Doe with Acme Construction. ")
    assert "Electrical" in draft.body.split("\n")[0] or "electrical" in draft.body.split("\n")[0]
    assert "Rough-in and trim for 8 townhouse units" in draft.body
    assert draft.line_items == []
    assert [r["email"] for r in draft.recipients] == [
        "quotes@coreandmain.example",
        "bids@ferguson.example",
    ]
