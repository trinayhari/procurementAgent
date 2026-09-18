"""Corpus loading + validation — the labelled plan sets the bench scores against.

The corpus lives OUTSIDE apps/api (repo root `bench-corpus/`, see
docs/eval-harness.md §1) and is owned by a different track, so everything here
treats it as untrusted input: a missing PDF is normal (they are gitignored and
some are local-only), a missing manifest means "not populated yet", and a
malformed one is reported as a list of human-readable problems rather than a
traceback. `load_corpus()` is the only function that raises, and only when the
manifest itself cannot be read.
"""
import json
import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from app.config import settings

# License strings a manifest entry may declare. Anything not clearly
# redistributable must be `local-only`, whose PDF is never committed.
LICENSES = (
    "public-domain-usgov",
    "public-domain",
    "cc-by",
    "cc-by-sa",
    "permissive-other",
    "local-only",
)

COMPLETENESS = ("full", "partial")

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")

MANIFEST_NAME = "manifest.json"
DEFAULT_QTY_TOLERANCE = 0.05


class CorpusError(RuntimeError):
    """The manifest is absent or unreadable — the corpus cannot be loaded at all."""


@dataclass(frozen=True)
class CorpusDoc:
    id: str
    title: str
    plan_type: str
    path: str  # ABSOLUTE path to the PDF
    exists: bool  # False when the gitignored PDF is not on this machine
    source_url: Optional[str] = None
    source_name: Optional[str] = None
    license: str = "local-only"
    retrieved_at: Optional[str] = None
    sha256: Optional[str] = None
    bytes: Optional[int] = None
    pages: Optional[int] = None
    has_text_layer: Optional[bool] = None
    tags: List[str] = field(default_factory=list)
    has_truth: bool = False


@dataclass(frozen=True)
class TruthItem:
    category: str
    name: str
    aliases: List[str] = field(default_factory=list)
    quantity: Optional[float] = None
    unit: Optional[str] = None
    qty_tolerance: float = DEFAULT_QTY_TOLERANCE
    required: bool = True
    source: Optional[str] = None


@dataclass(frozen=True)
class Truth:
    doc_id: str
    plan_type: str
    completeness: str  # "full" | "partial"
    notes: Optional[str] = None
    items: List[TruthItem] = field(default_factory=list)
    forbidden: List[dict] = field(default_factory=list)  # {"name": str, "why": str}


# --------------------------------------------------------------------- paths
def _repo_root() -> str:
    """Repo root, from apps/api/app/eval/corpus.py → four levels up."""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.abspath(os.path.join(here, "..", "..", "..", ".."))


def corpus_dir() -> str:
    """Absolute corpus root. Relative settings resolve from the REPO root."""
    configured = settings.bench_corpus_dir or "bench-corpus"
    if os.path.isabs(configured):
        return configured
    return os.path.abspath(os.path.join(_repo_root(), configured))


def manifest_path() -> str:
    return os.path.join(corpus_dir(), MANIFEST_NAME)


def corpus_exists() -> bool:
    """True when there is a manifest to load — the corpus may simply not be populated yet."""
    return os.path.isfile(manifest_path())


# ------------------------------------------------------------------ loading
def _read_manifest() -> dict:
    path = manifest_path()
    if not os.path.isfile(path):
        raise CorpusError(
            "No corpus manifest at {}. The corpus is not populated on this "
            "machine yet (bench-corpus/ is owned by the corpus track).".format(path)
        )
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        raise CorpusError("Corpus manifest at {} is unreadable: {}".format(path, exc))
    if not isinstance(data, dict) or not isinstance(data.get("documents"), list):
        raise CorpusError(
            "Corpus manifest at {} is malformed: expected an object with a "
            '"documents" array.'.format(path)
        )
    return data


def _truth_rel(entry: dict) -> Optional[str]:
    """The manifest's declared truth path, or the conventional one if it exists."""
    declared = entry.get("truth")
    if declared:
        return str(declared)
    conventional = os.path.join("truth", "{}.json".format(entry.get("id", "")))
    if os.path.isfile(os.path.join(corpus_dir(), conventional)):
        return conventional
    return None


def _to_doc(entry: dict, root: str) -> CorpusDoc:
    doc_id = str(entry.get("id", "")).strip()
    rel = str(entry.get("file") or "")
    path = os.path.abspath(os.path.join(root, rel)) if rel else ""
    truth_rel = _truth_rel(entry)
    tags = entry.get("tags") or []
    return CorpusDoc(
        id=doc_id,
        title=str(entry.get("title") or doc_id),
        plan_type=str(entry.get("plan_type") or ""),
        path=path,
        exists=bool(path) and os.path.isfile(path),
        source_url=entry.get("source_url"),
        source_name=entry.get("source_name"),
        license=str(entry.get("license") or "local-only"),
        retrieved_at=entry.get("retrieved_at"),
        sha256=entry.get("sha256"),
        bytes=entry.get("bytes"),
        pages=entry.get("pages"),
        has_text_layer=entry.get("has_text_layer"),
        tags=[str(t) for t in tags] if isinstance(tags, list) else [],
        has_truth=bool(truth_rel) and os.path.isfile(os.path.join(root, truth_rel)),
    )


def load_corpus() -> List[CorpusDoc]:
    """Every document in the manifest. Never raises on a missing PDF (exists=False)."""
    data = _read_manifest()
    root = corpus_dir()
    docs = []
    for entry in data["documents"]:
        if isinstance(entry, dict):
            docs.append(_to_doc(entry, root))
    return docs


def get_doc(doc_id: str) -> CorpusDoc:
    for doc in load_corpus():
        if doc.id == doc_id:
            return doc
    raise KeyError("Unknown corpus document '{}'".format(doc_id))


def _to_truth_item(raw: dict) -> TruthItem:
    aliases = raw.get("aliases") or []
    tol = raw.get("qty_tolerance")
    return TruthItem(
        category=str(raw.get("category") or ""),
        name=str(raw.get("name") or ""),
        aliases=[str(a) for a in aliases] if isinstance(aliases, list) else [],
        quantity=_as_float(raw.get("quantity")),
        unit=(str(raw["unit"]) if raw.get("unit") else None),
        qty_tolerance=DEFAULT_QTY_TOLERANCE if tol is None else float(tol),
        required=bool(raw.get("required", True)),
        source=(str(raw["source"]) if raw.get("source") else None),
    )


def _as_float(value) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def load_truth(doc_id: str) -> Optional[Truth]:
    """Ground truth for a document, or None when it is unlabelled.

    Raises CorpusError when a truth file is declared but unreadable — a silently
    skipped label would quietly inflate a run's apparent coverage.
    """
    doc_entry = None
    for entry in _read_manifest()["documents"]:
        if isinstance(entry, dict) and str(entry.get("id", "")) == doc_id:
            doc_entry = entry
            break
    if doc_entry is None:
        raise KeyError("Unknown corpus document '{}'".format(doc_id))

    rel = _truth_rel(doc_entry)
    if not rel:
        return None
    path = os.path.join(corpus_dir(), rel)
    if not os.path.isfile(path):
        raise CorpusError("Truth file declared for '{}' but missing: {}".format(doc_id, path))
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, ValueError) as exc:
        raise CorpusError("Truth file for '{}' is unreadable: {}".format(doc_id, exc))
    if not isinstance(raw, dict):
        raise CorpusError("Truth file for '{}' is malformed (expected an object)".format(doc_id))

    items = [_to_truth_item(i) for i in (raw.get("items") or []) if isinstance(i, dict)]
    forbidden = [f for f in (raw.get("forbidden") or []) if isinstance(f, dict)]
    return Truth(
        doc_id=str(raw.get("doc_id") or doc_id),
        plan_type=str(raw.get("plan_type") or doc_entry.get("plan_type") or ""),
        completeness=str(raw.get("completeness") or "partial"),
        notes=(str(raw["notes"]) if raw.get("notes") else None),
        items=items,
        forbidden=forbidden,
    )


# --------------------------------------------------------------- validation
def validate_corpus() -> List[str]:
    """Human-readable problems with the corpus. Empty list = clean.

    Never raises: an absent corpus is reported as a problem like any other, so
    `python -m app.eval validate` degrades to a message instead of a traceback
    while the corpus is still being assembled.
    """
    from app.services.extraction import registry  # local: keeps import cost off the hot path

    problems: List[str] = []
    if not corpus_exists():
        return [
            "corpus not populated: no manifest at {}".format(manifest_path()),
        ]
    try:
        data = _read_manifest()
    except CorpusError as exc:
        return [str(exc)]

    if data.get("version") != 1:
        problems.append("manifest: unexpected version {!r} (expected 1)".format(data.get("version")))

    known_types = {s.key for s in registry.all_specs()}
    seen: Dict[str, int] = {}
    root = corpus_dir()

    for i, entry in enumerate(data["documents"]):
        where = "documents[{}]".format(i)
        if not isinstance(entry, dict):
            problems.append("{}: not an object".format(where))
            continue
        doc_id = str(entry.get("id") or "")
        where = "{} ({})".format(where, doc_id or "no id")
        if not doc_id:
            problems.append("{}: missing id".format(where))
        elif not _ID_RE.match(doc_id):
            problems.append("{}: id must match ^[a-z0-9][a-z0-9-]*$".format(where))
        elif doc_id in seen:
            problems.append("{}: duplicate id (also at documents[{}])".format(where, seen[doc_id]))
        else:
            seen[doc_id] = i

        plan_type = str(entry.get("plan_type") or "")
        if not plan_type:
            problems.append("{}: missing plan_type".format(where))
        elif plan_type not in known_types:
            problems.append(
                "{}: plan_type '{}' is not registered (known: {})".format(
                    where, plan_type, ", ".join(sorted(known_types))
                )
            )

        if not entry.get("file"):
            problems.append("{}: missing file".format(where))
        if not entry.get("source_name") and not entry.get("source_url"):
            problems.append("{}: no provenance (source_name or source_url required)".format(where))
        license_ = str(entry.get("license") or "")
        if license_ not in LICENSES:
            problems.append(
                "{}: license '{}' is not one of {}".format(where, license_, ", ".join(LICENSES))
            )
        sha = entry.get("sha256")
        if sha and not _SHA_RE.match(str(sha).lower()):
            problems.append("{}: sha256 is not a 64-char hex digest".format(where))

        problems.extend(_validate_truth(entry, doc_id, plan_type, root, where))

    return problems


def _validate_truth(entry, doc_id, plan_type, root, where) -> List[str]:
    from app.services.extraction import registry

    problems: List[str] = []
    rel = _truth_rel(entry)
    if not rel:
        return problems  # unlabelled is legal — the doc is still smoke coverage
    path = os.path.join(root, rel)
    if not os.path.isfile(path):
        return ["{}: truth file missing: {}".format(where, path)]
    try:
        truth = load_truth(doc_id)
    except (CorpusError, KeyError, TypeError, ValueError) as exc:
        return ["{}: {}".format(where, exc)]
    if truth is None:
        return problems

    if truth.completeness not in COMPLETENESS:
        problems.append(
            "{}: truth completeness '{}' must be one of {}".format(
                where, truth.completeness, ", ".join(COMPLETENESS)
            )
        )
    if truth.doc_id != doc_id:
        problems.append("{}: truth doc_id '{}' does not match".format(where, truth.doc_id))
    # An EMPTY `full` truth is a negative control: the document is not a plan
    # set, the correct BOM is nothing, and every extracted line is an extra. An
    # empty `partial` truth measures nothing at all and is a mistake.
    if not truth.items and truth.completeness != "full":
        problems.append("{}: truth file has no items (only a `full` truth may be empty)".format(where))

    spec = registry.get(truth.plan_type or plan_type)
    valid_categories = {c.key for c in spec.categories} if spec else None
    for j, item in enumerate(truth.items):
        at = "{} truth.items[{}]".format(where, j)
        if not item.name:
            problems.append("{}: missing name".format(at))
        if not item.category:
            problems.append("{}: missing category".format(at))
        elif valid_categories is not None and item.category not in valid_categories:
            problems.append(
                "{}: category '{}' is not a category of plan type '{}' ({})".format(
                    at, item.category, truth.plan_type or plan_type,
                    ", ".join(sorted(valid_categories)) or "none",
                )
            )
        if not (0 <= item.qty_tolerance < 1):
            problems.append("{}: qty_tolerance {} must be in [0, 1)".format(at, item.qty_tolerance))
        if item.quantity is not None and item.quantity < 0:
            problems.append("{}: negative quantity".format(at))
    for j, f in enumerate(truth.forbidden):
        if not f.get("name"):
            problems.append("{} truth.forbidden[{}]: missing name".format(where, j))
    return problems


def coverage() -> dict:
    """Corpus headline counts, for `bench/status` and the CLI."""
    try:
        docs = load_corpus()
    except CorpusError:
        return {"corpus_dir": corpus_dir(), "documents": 0, "labelled": 0, "present": 0, "populated": False}
    return {
        "corpus_dir": corpus_dir(),
        "documents": len(docs),
        "labelled": sum(1 for d in docs if d.has_truth),
        "present": sum(1 for d in docs if d.exists),
        "populated": True,
    }
