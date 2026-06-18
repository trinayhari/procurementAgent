from enum import Enum


class Tone(str, Enum):
    """Semantic color token consumed by the frontend (maps to a CSS variable)."""

    blue = "blue"
    violet = "violet"
    gray = "gray"
    success = "success"
    warn = "warn"
    danger = "danger"
    ai = "ai"


class Stage(str, Enum):
    rfqs_out = "RFQs Out"
    quotes_in = "Quotes In"
    plans_review = "Plans Review"
    complete = "Complete"
    sourcing = "Sourcing"


class Risk(str, Enum):
    low = "Low"
    medium = "Medium"
    high = "High"


class RfqStatus(str, Enum):
    draft = "Draft"
    sent = "Sent"
    awaiting = "Awaiting"
    quoted = "Quoted"


class DocStatus(str, Enum):
    queued = "Queued"
    processing = "Processing"
    analyzed = "Analyzed"
    failed = "Failed"
