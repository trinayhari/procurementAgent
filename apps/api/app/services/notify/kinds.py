"""The dotted event names a Notice may carry (`Notice.kind`).

One constant per step of the loop so channels can key rendering (icon, tone,
button style) on a name every emitter agrees on. Add a kind here before
emitting it anywhere.
"""

INTAKE_RECEIVED = "intake.received"
"""A customer email or Slack post was picked up and attached to a project."""

INTAKE_NOTED = "intake.noted"
"""A customer message with no attachment was logged on the project as a note."""

BOM_DRAFTED = "bom.drafted"
"""Extraction finished: the document's bill of materials is ready to review."""

RFQ_SENT = "rfq.sent"
"""An RFQ went out to the package's suppliers."""

QUOTES_RECEIVED = "quotes.received"
"""Supplier replies were parsed into quotes for a package."""

AWARD_READY = "award.ready"
"""Enough quotes are in: a recommendation and an approval link were issued."""

AWARD_APPROVED = "award.approved"
"""A package award was approved (dashboard or approval link)."""

PO_ISSUED = "po.issued"
"""Purchase orders were numbered and sent to the winning suppliers."""

FOLLOWUP_SENT = "followup.sent"
"""A supplier who had not replied was nudged."""

ALL = (
    INTAKE_RECEIVED,
    INTAKE_NOTED,
    BOM_DRAFTED,
    RFQ_SENT,
    QUOTES_RECEIVED,
    AWARD_READY,
    AWARD_APPROVED,
    PO_ISSUED,
    FOLLOWUP_SENT,
)
