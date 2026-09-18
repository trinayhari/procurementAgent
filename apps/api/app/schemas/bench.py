"""Response models for the dev-only eval bench (see docs/eval-harness.md §3).

Two rules shape every model here:

  • **An undefined metric is `None`, never `0.0`.** A document where precision
    could not be computed (partial ground truth) and a document that scored zero
    are different facts, and the bench UI renders them differently (`—` vs
    `0.00`). So every metric field is `Optional[float]` with no default coercion.

  • **Mocked numbers are kept apart from real ones.** `metrics` and
    `mocked_metrics` are separate fields all the way out to the client; nothing
    in this module merges them or falls back from one to the other.

Python 3.8: `typing.Optional/List/Dict` only — PEP 604/585 annotations evaluate
at runtime inside Pydantic models and crash on 3.8.
"""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# --------------------------------------------------------------------- status
class BenchStatus(BaseModel):
    """Is the bench usable here, and would a run produce real numbers?"""

    enabled: bool
    corpus_dir: str  # ABSOLUTE, resolved from settings (which may be relative)
    docs: int
    labelled: int
    # False → no OpenAI key, so every extraction comes from the mock path and
    # nothing a run produces is an accuracy result.
    live_extraction: bool
    # Additive to the contract, for the empty state: how many PDFs are actually
    # on this machine (they are gitignored) and whether a manifest exists at all.
    present: int = 0
    populated: bool = False


# --------------------------------------------------------------------- corpus
class CorpusDocOut(BaseModel):
    id: str
    title: str
    plan_type: str
    path: str  # absolute path to the PDF
    exists: bool  # False when the gitignored PDF is not on this machine
    source_url: Optional[str] = None
    source_name: Optional[str] = None
    license: str
    retrieved_at: Optional[str] = None
    sha256: Optional[str] = None
    bytes: Optional[int] = None
    pages: Optional[int] = None
    has_text_layer: Optional[bool] = None
    tags: List[str] = []
    has_truth: bool = False


class CorpusOut(BaseModel):
    documents: List[CorpusDocOut] = []
    # Human-readable validation problems. A corpus that is not populated yet
    # reports exactly that here rather than failing the request.
    problems: List[str] = []


# ---------------------------------------------------------------- plan types
class PlanTypeCategoryOut(BaseModel):
    key: str
    label: str
    tone: str


class PlanTypeOut(BaseModel):
    key: str
    label: str
    description: str
    enabled: bool
    categories: List[PlanTypeCategoryOut] = []


# ------------------------------------------------------------------ variants
class VariantOut(BaseModel):
    id: str
    label: str
    description: Optional[str] = None
    settings: Dict[str, Any] = {}
    prompts: Dict[str, Any] = {}
    spec_overrides: Dict[str, Any] = {}
    # What `apply()` would reject. Non-empty → starting a run with this variant
    # is a 400; the UI can disable it instead of letting a run burn model calls.
    problems: List[str] = []


# ---------------------------------------------------------------- run inputs
class RunCreate(BaseModel):
    """A run request. Every field is a cost multiplier — see §6 of the contract."""

    doc_ids: List[str]
    variant_ids: List[str]
    plan_type: Optional[str] = None  # omitted → each doc's manifest plan_type
    trials: int = Field(default=1, ge=1, le=20)
    notes: Optional[str] = None  # batch label shared by the created runs


class RunCreated(BaseModel):
    run_ids: List[str]
    # Stated up front so the UI can show the price of the button it just pressed.
    extractions: int  # docs × variants × trials
    docs: int
    variants: int
    trials: int


# --------------------------------------------------------------- run outputs
class MetricsOut(BaseModel):
    """`scoring.aggregate()` — macro-averaged across the run's documents."""

    documents: int = 0
    precision: Optional[float] = None
    recall: Optional[float] = None
    f1: Optional[float] = None
    optional_recall: Optional[float] = None
    quantity_accuracy: Optional[float] = None
    unit_accuracy: Optional[float] = None
    category_accuracy: Optional[float] = None
    # Required items found with quantity AND unit right — the RFQ-ready share.
    usable_recall: Optional[float] = None
    hallucinations: int = 0
    # How many documents actually defined each metric — the denominator behind
    # the macro-average, so a 1-of-9 average is not read as a 9-document result.
    defined: Dict[str, int] = {}
    counts: Dict[str, int] = {}


class RunSummaryBlock(BaseModel):
    """The summary the runner stores on a finished run."""

    variant_id: str
    trials_total: int = 0
    trials_run: int = 0
    trials_ok: int = 0
    trials_failed: int = 0
    trials_mocked: int = 0
    trials_unlabelled: int = 0
    trials_scored: int = 0
    # True when ANY trial came from the mock path.
    mocked: bool = False
    latency_ms_avg: Optional[float] = None
    # LIVE, labelled trials only. `mocked_metrics` is deliberately a separate
    # field: a mocked number is not an accuracy result and must never be merged.
    metrics: Optional[MetricsOut] = None
    mocked_metrics: Optional[MetricsOut] = None
    note: Optional[str] = None  # why `metrics` is None, when it is


class RunSummaryOut(BaseModel):
    id: str
    created_at: str
    finished_at: Optional[str] = None
    status: str  # queued | running | done | failed | cancelled
    variant_id: str
    plan_type: Optional[str] = None
    doc_ids: List[str] = []
    trials: int = 1
    notes: Optional[str] = None
    progress_done: int = 0
    progress_total: int = 0
    error: Optional[str] = None
    summary: Optional[RunSummaryBlock] = None
    # Lifted out of `summary` so the runs LIST can badge MOCKED without fetching
    # each run's detail. None while the run has not produced a summary yet —
    # "not known yet" is not the same claim as "zero mocked trials".
    mocked_trials: Optional[int] = None


class MatchOut(BaseModel):
    """One truth/extracted pairing — the diff view's row."""

    kind: str  # hit | miss | extra | unknown | forbidden
    truth_index: Optional[int] = None
    extracted_index: Optional[int] = None
    score: float = 0.0
    category_ok: bool = False
    quantity_ok: Optional[bool] = None  # None when the truth has no quantity
    unit_ok: Optional[bool] = None
    truth_name: Optional[str] = None
    extracted_name: Optional[str] = None
    quantity_got: Optional[float] = None
    quantity_want: Optional[float] = None
    unit_got: Optional[str] = None
    unit_want: Optional[str] = None
    required: bool = True
    # Optional enrichment `scoring.ItemMatch` may or may not carry (that module
    # belongs to the eval core, not to us). Declared so it flows through to the
    # diff view when present, and stays null — never invented — when it isn't.
    truth_category: Optional[str] = None
    extracted_category: Optional[str] = None
    truth_source: Optional[str] = None
    qty_tolerance: Optional[float] = None
    forbidden_why: Optional[str] = None
    # got / want on a hit with both quantities — what a wrong quantity looks
    # like (0.125 = never scaled to 8 units; 3.0 = stacked text summed).
    quantity_ratio: Optional[float] = None


class DocScoreOut(BaseModel):
    doc_id: str
    plan_type: str
    # "full" | "partial", resolved from the ground-truth file. This is what
    # explains a null precision: on partial truth an unmatched extracted item is
    # unknown, not a false positive, so precision is deliberately unmeasurable.
    # None when the truth file could not be read at render time.
    completeness: Optional[str] = None
    precision: Optional[float] = None  # None on partial-completeness truth
    recall: Optional[float] = None
    f1: Optional[float] = None
    optional_recall: Optional[float] = None
    quantity_accuracy: Optional[float] = None
    unit_accuracy: Optional[float] = None
    category_accuracy: Optional[float] = None
    usable_recall: Optional[float] = None
    hallucinations: int = 0
    counts: Dict[str, int] = {}
    matches: List[MatchOut] = []


class TrialOut(BaseModel):
    id: str
    run_id: str
    doc_id: str
    variant_id: str
    trial_index: int = 0
    status: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    latency_ms: Optional[int] = None
    error: Optional[str] = None
    # Raw ExtractionResult.groups, so the UI can show what was actually read.
    groups: Optional[List[Dict[str, Any]]] = None
    summary_text: Optional[str] = None
    mocked: bool = False
    score: Optional[DocScoreOut] = None


class RunDetailOut(RunSummaryOut):
    trials_detail: List[TrialOut] = []


# ------------------------------------------------------------------- compare
class MetricDeltaOut(BaseModel):
    a: Optional[float] = None
    b: Optional[float] = None
    # None unless BOTH sides defined the metric — a delta against an
    # unmeasurable is not zero.
    delta: Optional[float] = None


class PerDocCompareOut(BaseModel):
    """One document, scored on both sides — WITH the match lists.

    The item-level lists are the point of compare: they say which materials a
    variant started finding and which it stopped finding, which no metric delta
    can tell you. Each side is the document's first live, scored trial in that
    run (`trials_a`/`trials_b` say how many there were), or null when the run
    produced no live score for it.
    """

    doc_id: str
    a: Optional[DocScoreOut] = None
    b: Optional[DocScoreOut] = None
    # True when either side had a mocked trial for this document — the row is a
    # plumbing check, not a comparison.
    mocked: bool = False
    trials_a: int = 0  # LIVE scored trials in run A for this document
    trials_b: int = 0


class CompareOut(BaseModel):
    a: RunSummaryOut
    b: RunSummaryOut
    deltas: Dict[str, MetricDeltaOut] = {}
    per_doc: List[PerDocCompareOut] = []
    # True when either run involved the mock path — the whole comparison is then
    # a plumbing check, not an accuracy comparison.
    mocked: bool = False


# ------------------------------------------------------------------- actions
class CancelResult(BaseModel):
    cancelled: bool


class DeleteResult(BaseModel):
    deleted: bool
