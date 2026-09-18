"""Match an extraction against ground truth and turn that into metrics.

The matcher is the load-bearing part of the whole bench: if it matches loosely,
every variant looks good; if it matches strictly, real improvements look like
noise. Two decisions carry most of the weight:

  • **The dimensional gate.** Size is the single most important token in a BOM,
    and fuzzy string matchers happily collapse `4" PVC` into `6" PVC` (>0.9 on
    any ratio you like). So a fuzzy match is rejected unless every DIMENSIONAL
    number in the truth name is present in the extracted name.

    A number's role decides whether it gates (see `dimensional_numbers`): `4"`,
    `Schedule 40` and `Class 350` are dimensions and must match, while the
    numerals inside a model code (`JEBL-30000LM-GL-120V-40K-80CRI`, `IP65`) or
    an equipment tag (`ATS1`, `MH-3`) identify a product, not a size, and must
    not. Treating all three alike is what made the first live run report one
    correctly-found fixture as BOTH a miss and an extra.

    The gate is directional: the truth's dimensions must appear in the
    extraction, not vice versa. Added spec detail is not a contradiction;
    DROPPED spec detail is (an extraction that says "PVC Conduit" has not found
    `2" Schedule 40 PVC Conduit`, it has found something vaguer).

  • **Category is recorded, not gating.** Finding the right hydrant under the
    wrong category is a *smaller* failure than not finding it, and collapsing
    the two into one number hides which one you fixed.

Everything is deterministic — no model call. An LLM judge would be a flag, never
the default, because the bench has to be reproducible to be worth anything.
"""
import math
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from app.eval.corpus import Truth, TruthItem

try:  # optional fast path; the stdlib fallback is the contract
    from rapidfuzz import fuzz as _rf_fuzz
except ImportError:  # pragma: no cover - rapidfuzz is not a dependency
    _rf_fuzz = None

from difflib import SequenceMatcher

# A fuzzy pair below this is not a match. Deliberately high: with the numeric
# gate already in place, what is left to absorb is wording, not size.
FUZZY_THRESHOLD = 0.82

# Units that mean the same thing on a plan set. Anything not listed compares
# on its uppercased self, so an unknown unit is never silently "equal".
_UNIT_ALIASES = {
    "LF": "LF", "FT": "LF", "FEET": "LF", "FOOT": "LF", "LIN FT": "LF",
    "LINFT": "LF", "LINEAR FEET": "LF", "LINEAL FEET": "LF", "L.F.": "LF",
    "EA": "EA", "EACH": "EA", "EAS": "EA", "PC": "EA", "PCS": "EA", "PIECE": "EA",
    "PIECES": "EA", "NO": "EA", "NO.": "EA", "CNT": "EA", "COUNT": "EA",
    "SY": "SY", "SQYD": "SY", "SQ YD": "SY", "SQ. YD.": "SY", "SYD": "SY",
    "SQUARE YARDS": "SY", "S.Y.": "SY",
    "SF": "SF", "SQFT": "SF", "SQ FT": "SF", "SQ. FT.": "SF", "SQUARE FEET": "SF",
    "S.F.": "SF",
    "CY": "CY", "CUYD": "CY", "CU YD": "CY", "CU. YD.": "CY", "CUBIC YARDS": "CY",
    "C.Y.": "CY",
    "TON": "TON", "TONS": "TON", "TN": "TON",
    "LB": "LB", "LBS": "LB", "POUND": "LB", "POUNDS": "LB",
    "GAL": "GAL", "GALLON": "GAL", "GALLONS": "GAL",
    "LS": "LS", "LUMP SUM": "LS",
}

_INCH_RE = re.compile(u'["”″]')  # ", ”, ″ — all mean inches on a plan
_TRAILING_PAREN_RE = re.compile(r"\s*\([^()]*\)\s*$")
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
_QTY_RE = re.compile(r"^\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*(.*)$")
# Quantity placeholders the extraction pipeline renders for "unknown".
_NO_QTY = {"", "-", "--", u"—", u"–", "n/a", "na", "none", "null", "?"}

# Suffixes that make a glued numeral a MEASUREMENT rather than a product code:
# `12awg`, `480v`, `600a`, `3ph` gate; `30000lm`, `80cri`, `40k` (lumens, colour
# rendering, colour temperature — catalogue attributes) do not.
_DIMENSION_SUFFIXES = frozenset({
    "inch", "in", "mm", "cm", "m", "ft", "foot", "feet", "lf", "sf", "sy", "cy",
    "ea", "awg", "ga", "gauge", "kcmil", "mcm", "v", "kv", "volt", "volts",
    "a", "amp", "amps", "ph", "phase", "psi", "ton", "tons", "lb", "lbs", "gal",
    "w", "kw", "kva", "hp", "gpm", "deg", "degree", "oc",
})

# A bare number: the plain dimensional case — `4 inch`, `Schedule 40`, `Class 350`.
_BARE_NUMBER_RE = re.compile(r"^(\d+(?:\.\d+)?)$")
# A number glued to a letter suffix — dimensional only if the suffix is a unit.
_NUMBER_UNIT_RE = re.compile(r"^(\d+(?:\.\d+)?)([a-z]+)$")
# Letters then digits with no separator: an equipment tag or catalogue code —
# `ats1`, `mts1`, `ip65`, `c900`. Identifies a product, never a dimension.
_IDENTIFIER_RE = re.compile(r"^[a-z]{1,4}\d+[a-z0-9]*$")
# A hyphenated equipment tag: a short letter prefix and a number — `mh-3`, `p-2`.
_TAG_RE = re.compile(r"^[a-z]{1,3}(?:-\d+)+$")
# Tokenisation for role analysis. Unlike normalize_name this KEEPS hyphens, so a
# model code stays one token instead of dissolving into stray numerals.
_ROLE_SPLIT_RE = re.compile(r"[^a-z0-9.#\-]+")


@dataclass(frozen=True)
class ExtractedRef:
    """One flattened extracted line item, with the position the matcher uses.

    Track B renders miss/extra lists by index, so this flattening order (group
    order, then item order — the same order `_to_groups` emits) is part of the
    contract: `ItemMatch.extracted_index` indexes into `flatten_extracted()`.
    """

    index: int
    name: str
    quantity: Optional[float] = None
    unit: Optional[str] = None
    category: Optional[str] = None
    group: str = ""


@dataclass(frozen=True)
class ItemMatch:
    truth_index: Optional[int]  # None → extracted item with no truth counterpart
    extracted_index: Optional[int]  # None → truth item that was missed
    score: float  # 0..1 name similarity that produced the match
    category_ok: bool
    quantity_ok: Optional[bool]  # None when truth has no quantity
    unit_ok: Optional[bool]
    kind: str  # "hit" | "miss" | "extra" | "unknown" | "forbidden"
    # Additive: everything the diff view needs to explain a failure on its own,
    # without re-flattening the extraction or re-reading the truth file. Each is
    # populated only where the fact genuinely exists at match time — an "extra"
    # has no truth counterpart, so its truth-side fields stay None.
    truth_name: Optional[str] = None
    extracted_name: Optional[str] = None
    quantity_got: Optional[float] = None
    quantity_want: Optional[float] = None
    unit_got: Optional[str] = None
    unit_want: Optional[str] = None
    required: bool = True
    # Where in the plan set the truth was taken from — what to go look at to
    # confirm a miss. Present whenever there IS a truth item (hit and miss).
    truth_source: Optional[str] = None
    # The tolerance that governs this item, so "off by -28% · tol ±5%" reads as
    # a quantity problem or a tolerance problem. Same rule: truth-side only.
    qty_tolerance: Optional[float] = None
    # Why this item is a known hallucination here — kind="forbidden" only. A
    # hallucination is only actionable once you know why it is wrong.
    forbidden_why: Optional[str] = None
    # The two sides of `category_ok`, so the UI can say "storm → water" instead
    # of just "wrong category".
    truth_category: Optional[str] = None
    extracted_category: Optional[str] = None
    # got / want, when both exist and want is non-zero. The single most useful
    # number for diagnosing a WRONG quantity: 0.125 is a typical-unit count that
    # was never scaled to the 8-unit building; 3.0 on a CAD set is the stacked
    # text layer summed three times; 2.0 is plan + profile added together.
    quantity_ratio: Optional[float] = None


@dataclass(frozen=True)
class DocScore:
    doc_id: str
    plan_type: str
    precision: Optional[float]  # None on partial-completeness truth
    recall: Optional[float]  # None when the truth has no required items
    f1: Optional[float]
    optional_recall: Optional[float]
    quantity_accuracy: Optional[float]  # among hits with a truth quantity
    unit_accuracy: Optional[float]
    category_accuracy: Optional[float]  # among hits
    hallucinations: int  # forbidden matches
    counts: dict
    matches: List[ItemMatch] = field(default_factory=list)
    # Required items found with EVERY field the truth states correct (quantity
    # within tolerance, unit equal). Recall says the model saw the item; this
    # says the line could go on an RFQ as-is — which is what downstream needs.
    usable_recall: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "doc_id": self.doc_id,
            "plan_type": self.plan_type,
            "precision": self.precision,
            "recall": self.recall,
            "f1": self.f1,
            "optional_recall": self.optional_recall,
            "quantity_accuracy": self.quantity_accuracy,
            "unit_accuracy": self.unit_accuracy,
            "category_accuracy": self.category_accuracy,
            "usable_recall": self.usable_recall,
            "hallucinations": self.hallucinations,
            "counts": dict(self.counts),
            "matches": [vars(m).copy() for m in self.matches],
        }


METRIC_KEYS = (
    "precision",
    "recall",
    "f1",
    "optional_recall",
    "quantity_accuracy",
    "unit_accuracy",
    "category_accuracy",
    "usable_recall",
)

# A wrong quantity whose got/want ratio sits within this of an integer k >= 2
# (or 1/k) is a SCALE error — a per-unit count not multiplied up, or a stacked
# text layer summed — rather than a misread number.
SCALE_ERROR_TOLERANCE = 0.1
SCALE_ERROR_MAX_FACTOR = 24


def scale_factor(ratio: Optional[float]) -> Optional[int]:
    """The integer k such that got ≈ want × k or got ≈ want / k; None otherwise.

    Positive k means the extraction is k times TOO BIG; negative k means k
    times too small. Ratios near 1 are not scale errors and return None.
    """
    if ratio is None or ratio <= 0:
        return None
    too_big = ratio >= 1.0
    magnitude = ratio if too_big else 1.0 / ratio
    k = int(round(magnitude))
    if k < 2 or k > SCALE_ERROR_MAX_FACTOR:
        return None
    if abs(magnitude - k) > k * SCALE_ERROR_TOLERANCE:
        return None
    return k if too_big else -k


# ------------------------------------------------------------ normalisation
def normalize_name(name: Optional[str]) -> str:
    """Lowercase, expand inch marks, drop a trailing parenthetical, keep numbers."""
    s = (name or "").lower()
    s = _INCH_RE.sub(" inch ", s)
    while True:
        stripped = _TRAILING_PAREN_RE.sub("", s)
        if stripped == s:
            break
        s = stripped
    s = s.replace(u"°", " degree ").replace("%", " percent ").replace("&", " and ")
    s = re.sub(r"[^a-z0-9.]+", " ", s)
    # Keep decimal points, drop sentence/abbreviation dots ("no." → "no").
    s = re.sub(r"(?<!\d)\.", " ", s)
    s = re.sub(r"\.(?!\d)", " ", s)
    return " ".join(_singular(t) for t in s.split() if t)


def _singular(token: str) -> str:
    """Trivial de-pluralisation only — never touch numbers or short words."""
    if not token.isalpha() or len(token) <= 3:
        return token
    if token.endswith("ss") or token.endswith("us") or token.endswith("is"):
        return token
    if token.endswith("es") and len(token) > 4 and token[:-2].endswith(("s", "x", "z", "ch", "sh")):
        return token[:-2]
    if token.endswith("s"):
        return token[:-1]
    return token


def _canonical_number(raw: str) -> str:
    """'12.0' and '12' are the same number."""
    value = float(raw)
    return str(int(value)) if value.is_integer() else repr(value)


# Construction fractions are always over a power of two (1/2", 3/4", 7/16",
# 23/32"); anything else written a/b is a ratio or a pair (208/120V), not a size.
_FRACTION_DENOMINATORS = frozenset({2, 4, 8, 16, 32, 64})
_MIXED_NUMBER_RE = re.compile(r"(?<![\d.])(\d+)-(\d+)/(\d+)(?![\d/])")
_FRACTION_RE = re.compile(r"(?<![\d.\-/])(\d+)/(\d+)(?![\d/])")
# `(2)` in a material name is a ply / bar / conductor COUNT, not a size.
_PAREN_COUNT_RE = re.compile(r"\((\d+)\)")
# `@ 16" O.C.` / `at 24 in. on center` — a spacing, stated by the truth, that an
# extraction may legitimately leave off the line item.
_SPACING_RE = re.compile(
    r"(?:@|\bat)\s*(\d+(?:\.\d+)?)\s*(?:[\"”″']|inch(?:es)?\b|in\b\.?|ft\b\.?)?\s*"
    r"(?:o\.?\s?c\.?\b|on\s+center\b)"
)
# `2x6`, `6x12`, `4x4x8` — a lumber / structure size written as one token.
_SIZE_PRODUCT_RE = re.compile(
    r"(?<![a-z0-9.])(\d+(?:\.\d+)?)x(\d+(?:\.\d+)?)(?:x(\d+(?:\.\d+)?))?(?![a-z0-9])"
)
# `3,000 psi`, `1,450 LF` — a thousands separator, not two numbers.
_THOUSANDS_RE = re.compile(r"(?<=\d),(?=\d{3}\b)")
# `1'-3"`, `2'-0"`, `1' 6"` — feet-and-inches is ONE dimension, in inches.
_FEET_INCHES_RE = re.compile(r"(?<![\d.])(\d+)'\s*-?\s*(\d+(?:\.\d+)?)\s*[\"”″]")
# `r-3067-7004-v`, `sthd-14`: letters, then numeric segments — a catalogue code.
_ALPHA_LED_CODE_RE = re.compile(r"^([a-z]+)(?:-([a-z0-9]+))+$")


def _fraction_value(whole: str, num: str, den: str) -> Optional[float]:
    d = int(den)
    n = int(num)
    if d not in _FRACTION_DENOMINATORS or n >= d:
        return None
    return int(whole or 0) + n / float(d)


def _prepass(text: str, codes: Dict[str, set]) -> str:
    """Rewrite the notations that make a numeral LOOK like a size when it is not.

    Runs on the raw lowercased name, before tokenisation, and records what it
    removes as conflict-only code values (present on both sides and different →
    the two names are different things; present on one side only → nothing).

      • trailing parentheticals are notes (`(feeder mark 1, 200A/4W)`), exactly
        as `normalize_name` treats them;
      • `(2)` is a ply / bar count → `count`;
      • `@ 16" O.C.` is a spacing → `oc`;
      • `1/2"`, `1-3/4"` are ONE dimension each, not two or three, and `1/2"`
        must not be satisfied by the 1 and 2 in `2-1/2"`; `3/0` (AWG) is a
        gauge, not a fraction → `/0`;
      • `2x6` is two dimensions, not a token the scanner cannot read.
    """
    while True:
        stripped = _TRAILING_PAREN_RE.sub("", text)
        if stripped == text:
            break
        text = stripped

    def take_count(m):
        codes.setdefault("count", set()).add(_canonical_number(m.group(1)))
        return " "

    def take_spacing(m):
        codes.setdefault("oc", set()).add(_canonical_number(m.group(1)))
        return " "

    def take_mixed(m):
        value = _fraction_value(m.group(1), m.group(2), m.group(3))
        if value is None:
            return m.group(0)
        return " " + _canonical_number(str(value)) + " "

    def take_fraction(m):
        if int(m.group(2)) == 0:  # 1/0 … 4/0: wire gauge
            codes.setdefault("/0", set()).add(_canonical_number(m.group(1)))
            return " "
        value = _fraction_value("", m.group(1), m.group(2))
        if value is None:
            return m.group(0)
        return " " + _canonical_number(str(value)) + " "

    text = _THOUSANDS_RE.sub("", text)
    text = _FEET_INCHES_RE.sub(
        lambda m: " " + _canonical_number(str(int(m.group(1)) * 12 + float(m.group(2)))) + '" ',
        text,
    )
    text = _PAREN_COUNT_RE.sub(take_count, text)
    text = _SPACING_RE.sub(take_spacing, text)
    text = _MIXED_NUMBER_RE.sub(take_mixed, text)
    text = _FRACTION_RE.sub(take_fraction, text)
    text = _SIZE_PRODUCT_RE.sub(
        lambda m: " " + " x ".join(g for g in m.groups() if g) + " ", text
    )
    return text


def _analyse(name: Optional[str]) -> Tuple[Dict[str, int], Dict[str, set]]:
    """Split a raw name's numerals into dimensions and product-code values.

    Returns ({canonical number: count}, {code key: {values}}). The second is how
    `ATS1` and `30000LM` are kept honest without gating on their presence: they
    only ever conflict with the SAME key on the other side.
    """
    dims: Dict[str, int] = {}
    codes: Dict[str, set] = {}
    text = _prepass((name or "").lower(), codes)
    text = _INCH_RE.sub(" inch ", text)
    text = text.replace(u"°", " degree ").replace("%", " percent ")
    for token in _ROLE_SPLIT_RE.split(text):
        _scan_token(token, dims, codes)
    return dims, codes


def _scan_token(token: str, dims: Dict[str, int], codes: Dict[str, set]) -> None:
    """Classify one raw token and record what it contributes."""
    token = token.strip("-.")
    if not token:
        return
    token = token.lstrip("#")
    # `8"x6"` normalises to `8 inch x6 inch`: the x binds to the second size.
    if len(token) > 1 and token[0] == "x" and token[1].isdigit():
        token = token[1:]

    if "-" in token:
        segments = [s for s in token.split("-") if s]
        # A model code (`jebl-30000lm-gl-120v-40k-80cri`) or an equipment tag
        # (`mh-3`): its numerals identify a product, so they never gate on
        # presence — but they are still recorded as code values, so the same key
        # with a different value on the other side is a contradiction.
        if _TAG_RE.match(token):  # `mh-3`, `p-2` — keyed by the tag's prefix
            for segment in segments[1:]:
                codes.setdefault(segments[0], set()).add(_canonical_number(segment))
            return
        mixed = [s for s in segments if any(c.isdigit() for c in s) and any(c.isalpha() for c in s)]
        if mixed and len(segments) > 1:
            for segment in segments:
                _scan_code(segment, codes)
            return
        # `r-3067-7004-v`: a letter prefix followed by numeric segments is a
        # catalogue number (Neenah castings, Simpson connectors), keyed by
        # its prefix so `R-3067` and `R-1550` can contradict each other.
        if _ALPHA_LED_CODE_RE.match(token) and any(s.isdigit() for s in segments[1:]):
            for segment in segments[1:]:
                if segment.isdigit():
                    codes.setdefault(segments[0], set()).add(_canonical_number(segment))
            return
        for segment in segments:
            _scan_token(segment, dims, codes)
        return

    if _BARE_NUMBER_RE.match(token):
        number = _canonical_number(token)
        dims[number] = dims.get(number, 0) + 1
        return

    unit_match = _NUMBER_UNIT_RE.match(token)
    if unit_match:
        if unit_match.group(2) in _DIMENSION_SUFFIXES:
            number = _canonical_number(unit_match.group(1))
            dims[number] = dims.get(number, 0) + 1
            # Also keyed by its unit: `600A` and `800A` are directly comparable,
            # so they can contradict each other even when an alias matched.
            codes.setdefault(unit_match.group(2), set()).add(number)
        else:
            # `30000lm`, `80cri`, `40k` — a catalogue attribute, keyed by its unit.
            codes.setdefault(unit_match.group(2), set()).add(
                _canonical_number(unit_match.group(1))
            )
        return

    _scan_code(token, codes)


def _scan_code(token: str, codes: Dict[str, set]) -> None:
    """Record `ats1` / `ip65` / `c900` / `30000lm` as {prefix or unit: value}."""
    identifier = re.match(r"^([a-z]{1,4})(\d+)[a-z0-9]*$", token)
    if identifier:
        codes.setdefault(identifier.group(1), set()).add(_canonical_number(identifier.group(2)))
        return
    attribute = _NUMBER_UNIT_RE.match(token)
    if attribute:
        codes.setdefault(attribute.group(2), set()).add(_canonical_number(attribute.group(1)))
        return
    if _BARE_NUMBER_RE.match(token):
        codes.setdefault("", set()).add(_canonical_number(token))


def code_values(name: Optional[str]) -> Dict[str, set]:
    """Product-code / tag numerals, keyed so only like compares with like."""
    return _analyse(name)[1]


def dimensional_numbers(name: Optional[str]) -> Dict[str, int]:
    """The numbers in a material name that carry DIMENSIONAL meaning, with counts.

    Counts, not a set, so `8"x8" Tee` (two 8s) cannot be satisfied by `8"x6" Tee`
    (one 8) — fitting sizes come in pairs and collapsing them loses the second.

    A numeral counts when it stands alone (`4`, `Schedule 40`, `Class 350`) or is
    glued to a unit (`12awg`, `480v`). It does NOT count when it lives inside a
    catalogue code or an equipment tag, because those identify a product rather
    than measure one. Runs on the RAW name: normalisation dissolves the hyphens
    that distinguish `MH-3` (a tag) from `3` (a dimension).
    """
    return _analyse(name)[0]


def _satisfied(wanted: Dict[str, int], got: Dict[str, int]) -> bool:
    for number, count in wanted.items():
        if got.get(number, 0) < count:
            return False
    return True


def _codes_agree(a: Dict[str, set], b: Dict[str, set]) -> bool:
    """False when both names carry the SAME code key with disjoint values.

    `MH-3` vs `MH-4` and `30000LM` vs `20000LM` are different products even
    though the numeral is not a dimension. Only a shared key can conflict, so a
    code that appears on one side alone (`IP65`) still never blocks a match.
    """
    for key, values in a.items():
        other = b.get(key)
        if other and not (values & other):
            return False
    return True


def gate_ok(truth_name: str, extracted_name: str) -> bool:
    """The full gate: dimensions present, and no contradicting product code.

    Directional. Extra spec detail on the extracted side is fine — `IP65,
    Duracoat Finish` does not contradict anything. A dimension the truth states
    and the extraction lacks means it found something vaguer, not this item.
    """
    truth_dims, truth_codes = _analyse(truth_name)
    got_dims, got_codes = _analyse(extracted_name)
    return _satisfied(truth_dims, got_dims) and _codes_agree(truth_codes, got_codes)


class _Prepared(object):
    """A name reduced once: normalised form, dimensions, and code values.

    Matching is O(truth × extracted), so these are computed per name, not per pair.
    """

    __slots__ = ("norm", "dims", "codes")

    def __init__(self, name):
        self.norm = normalize_name(name)
        self.dims, self.codes = _analyse(name)


def normalize_unit(unit: Optional[str]) -> Optional[str]:
    if unit is None:
        return None
    key = " ".join(str(unit).strip().upper().split())
    if not key:
        return None
    return _UNIT_ALIASES.get(key, _UNIT_ALIASES.get(key.replace(".", ""), key))


def _ratio(a: str, b: str) -> float:
    if _rf_fuzz is not None:
        return _rf_fuzz.ratio(a, b) / 100.0
    return SequenceMatcher(None, a, b).ratio()


def token_set_ratio(a: str, b: str) -> float:
    """rapidfuzz-style token-set ratio, on stdlib difflib when rapidfuzz is absent.

    Order-insensitive and forgiving of one side carrying extra qualifiers, which
    is exactly how estimators and models differ in phrasing.
    """
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if _rf_fuzz is not None:
        return _rf_fuzz.token_set_ratio(a, b) / 100.0
    ta, tb = set(a.split()), set(b.split())
    shared = " ".join(sorted(ta & tb))
    only_a = (shared + " " + " ".join(sorted(ta - tb))).strip()
    only_b = (shared + " " + " ".join(sorted(tb - ta))).strip()
    if not shared:
        return _ratio(only_a, only_b)
    return max(_ratio(shared, only_a), _ratio(shared, only_b), _ratio(only_a, only_b))


def _similarity(truth: _Prepared, extracted: _Prepared) -> float:
    if not truth.norm or not extracted.norm:
        return 0.0
    if truth.norm == extracted.norm:
        return 1.0
    if not _satisfied(truth.dims, extracted.dims):
        return 0.0
    if not _codes_agree(truth.codes, extracted.codes):
        return 0.0
    return token_set_ratio(truth.norm, extracted.norm)


def name_similarity(truth_name: str, extracted_name: str) -> float:
    """Similarity of a truth name and an extracted name, with the dimensional gate.

    DIRECTIONAL: argument order is (truth, extracted). Returns 0.0 when the
    extraction is missing a dimension the truth states, however similar the
    strings are — `4" PVC` vs `6" PVC` is a different material, not a near miss.
    Takes RAW names; normalisation happens inside (it destroys the hyphens the
    gate needs to tell a model code from a size).
    """
    return _similarity(_Prepared(truth_name), _Prepared(extracted_name))


# ------------------------------------------------------------- flattening
def _parse_quantity(display) -> Tuple[Optional[float], Optional[str]]:
    """Split the pipeline's quantity display ('1,450 LF', '—') into value + unit."""
    if display is None:
        return None, None
    if isinstance(display, (int, float)) and not isinstance(display, bool):
        return float(display), None
    text = str(display).strip()
    if text.lower() in _NO_QTY:
        return None, None
    m = _QTY_RE.match(text)
    if not m:
        return None, (text or None)
    try:
        value = float(m.group(1).replace(",", ""))
    except ValueError:
        return None, None
    unit = m.group(2).strip() or None
    return value, unit


def _category_lookup(spec) -> Dict[str, str]:
    """label/key (lowercased) → category key, so a group can name its category."""
    out = {}
    if spec is None:
        return out
    for cat in getattr(spec, "categories", []) or []:
        out[str(cat.label).strip().lower()] = cat.key
        out[str(cat.key).strip().lower()] = cat.key
    return out


def flatten_extracted(extracted_groups: Sequence[dict], spec=None) -> List[ExtractedRef]:
    """Flatten BOM groups into indexed line items, in the order the pipeline emits."""
    by_label = _category_lookup(spec)
    refs: List[ExtractedRef] = []
    for group in extracted_groups or []:
        if not isinstance(group, dict):
            continue
        label = str(group.get("group") or group.get("label") or "")
        category = group.get("category") or by_label.get(label.strip().lower()) or None
        for item in group.get("items") or []:
            if not isinstance(item, dict):
                continue
            name = item.get("n", item.get("name"))
            if name is None:
                continue
            if "quantity" in item or "unit" in item:
                quantity = item.get("quantity")
                quantity = None if isinstance(quantity, bool) else quantity
                unit = item.get("unit")
                try:
                    quantity = None if quantity is None else float(quantity)
                except (TypeError, ValueError):
                    quantity, unit = _parse_quantity(item.get("q"))
            else:
                quantity, unit = _parse_quantity(item.get("q"))
            refs.append(
                ExtractedRef(
                    index=len(refs),
                    name=str(name),
                    quantity=quantity,
                    unit=(str(unit) if unit else None),
                    category=category,
                    group=label,
                )
            )
    return refs


# ----------------------------------------------------------------- matching
def _prepare_all(names) -> List[_Prepared]:
    return [_Prepared(n) for n in names if n]


def _merged_codes(candidates: List[_Prepared]) -> Dict[str, set]:
    """Union of the code/unit values stated anywhere in one truth item."""
    merged: Dict[str, set] = {}
    for candidate in candidates:
        for key, values in candidate.codes.items():
            merged.setdefault(key, set()).update(values)
    return merged


def _best_score(candidates: List[_Prepared], extracted: _Prepared) -> float:
    """Best similarity of an extracted name against a truth name or any alias.

    An alias is a second chance at the SAME item, not a looser gate. Two things
    keep it honest:
      • each candidate is gated on its own dimensions, so `12" DI Pipe` can be
        aliased to `12 inch ductile iron pipe` without letting an 8" line in;
      • a value the ITEM states anywhere still may not be contradicted. Truth
        files carry short aliases (`MSB`), and token-set similarity scores a
        bare acronym against any name containing it at 1.0 — without this, a
        `600A` switchboard would happily match an `800A` one through its alias.
    """
    if not _codes_agree(_merged_codes(candidates), extracted.codes):
        return 0.0
    best = 0.0
    for candidate in candidates:
        score = _similarity(candidate, extracted)
        if score >= 1.0:
            return 1.0
        best = max(best, score)
    return best


def _quantity_ok(want: Optional[float], got: Optional[float], tolerance: float) -> Optional[bool]:
    if want is None:
        return None  # the truth does not score this field
    if got is None:
        return False  # a stated quantity that was not extracted is a failure
    return abs(got - want) <= abs(want) * tolerance + 1e-9


def _quantity_ratio(want: Optional[float], got: Optional[float]) -> Optional[float]:
    if want is None or got is None or want == 0:
        return None
    return got / float(want)


def _unit_ok(want: Optional[str], got: Optional[str]) -> Optional[bool]:
    if want is None:
        return None
    return normalize_unit(want) == normalize_unit(got)


def score_document(extracted_groups: Sequence[dict], truth: Truth, spec=None) -> DocScore:
    """Score one extraction against one document's ground truth.

    `spec` is the PlanTypeSpec the extraction ran under; it maps a group's UI
    label back to its category key. Passing None simply leaves `category_ok`
    resting on whatever the groups themselves declare.
    """
    refs = flatten_extracted(extracted_groups, spec)
    # Prepared from the RAW names: the gate reads hyphens that normalisation drops.
    prepared = [_Prepared(r.name) for r in refs]
    truth_prepared = [
        _prepare_all([i.name] + list(i.aliases or [])) for i in truth.items
    ]
    matches: List[ItemMatch] = []

    # 1. Forbidden wins outright: a known hallucination is never merely an extra.
    forbidden_hit: Dict[int, Tuple[dict, float]] = {}
    forbidden_prepared = [
        (entry, _prepare_all([entry.get("name")] + list(entry.get("aliases") or [])))
        for entry in truth.forbidden or []
    ]
    for ref in refs:
        best_entry, best_score = None, 0.0
        for entry, candidates in forbidden_prepared:
            score = _best_score(candidates, prepared[ref.index])
            if score > best_score:
                best_entry, best_score = entry, score
        if best_entry is not None and best_score >= FUZZY_THRESHOLD:
            forbidden_hit[ref.index] = (best_entry, best_score)

    # 2. Every candidate pair above threshold, then greedy one-to-one by score.
    pairs: List[Tuple[float, int, int]] = []
    for t_i, item in enumerate(truth.items):
        for ref in refs:
            if ref.index in forbidden_hit:
                continue
            score = _best_score(truth_prepared[t_i], prepared[ref.index])
            if score >= FUZZY_THRESHOLD:
                pairs.append((score, t_i, ref.index))
    pairs.sort(key=lambda p: (-p[0], p[1], p[2]))

    truth_taken: Dict[int, int] = {}
    ext_taken: Dict[int, int] = {}
    for score, t_i, e_i in pairs:
        if t_i in truth_taken or e_i in ext_taken:
            continue
        truth_taken[t_i] = e_i
        ext_taken[e_i] = t_i
        item, ref = truth.items[t_i], refs[e_i]
        matches.append(
            ItemMatch(
                truth_index=t_i,
                extracted_index=e_i,
                score=score,
                category_ok=(ref.category == item.category),
                quantity_ok=_quantity_ok(item.quantity, ref.quantity, item.qty_tolerance),
                unit_ok=_unit_ok(item.unit, ref.unit),
                kind="hit",
                truth_name=item.name,
                extracted_name=ref.name,
                quantity_got=ref.quantity,
                quantity_want=item.quantity,
                unit_got=ref.unit,
                unit_want=item.unit,
                required=item.required,
                truth_source=item.source,
                qty_tolerance=item.qty_tolerance,
                truth_category=item.category or None,
                extracted_category=ref.category,
                quantity_ratio=_quantity_ratio(item.quantity, ref.quantity),
            )
        )

    # 3. Whatever is left over on each side.
    for t_i, item in enumerate(truth.items):
        if t_i in truth_taken:
            continue
        matches.append(
            ItemMatch(
                truth_index=t_i,
                extracted_index=None,
                score=0.0,
                category_ok=False,
                quantity_ok=None,
                unit_ok=None,
                kind="miss",
                truth_name=item.name,
                quantity_want=item.quantity,
                unit_want=item.unit,
                required=item.required,
                truth_source=item.source,
                qty_tolerance=item.qty_tolerance,
                truth_category=item.category or None,
            )
        )

    full = truth.completeness == "full"
    for ref in refs:
        if ref.index in ext_taken:
            continue
        if ref.index in forbidden_hit:
            entry, score = forbidden_hit[ref.index]
            matches.append(
                ItemMatch(
                    truth_index=None,
                    extracted_index=ref.index,
                    score=score,
                    category_ok=False,
                    quantity_ok=None,
                    unit_ok=None,
                    kind="forbidden",
                    truth_name=str(entry.get("name") or ""),
                    extracted_name=ref.name,
                    quantity_got=ref.quantity,
                    unit_got=ref.unit,
                    forbidden_why=(str(entry["why"]) if entry.get("why") else None),
                    extracted_category=ref.category,
                )
            )
            continue
        # On `partial` truth an unmatched item is UNKNOWN, not wrong: the truth
        # may simply not cover it, and calling that a false positive would
        # punish a correct extraction.
        matches.append(
            ItemMatch(
                truth_index=None,
                extracted_index=ref.index,
                score=0.0,
                category_ok=False,
                quantity_ok=None,
                unit_ok=None,
                kind="extra" if full else "unknown",
                extracted_name=ref.name,
                quantity_got=ref.quantity,
                unit_got=ref.unit,
                extracted_category=ref.category,
            )
        )

    return _metrics(truth, refs, matches, full)


def _metrics(truth: Truth, refs, matches: List[ItemMatch], full: bool) -> DocScore:
    hits = [m for m in matches if m.kind == "hit"]
    required_hits = [m for m in hits if m.required]
    optional_hits = [m for m in hits if not m.required]
    extras = [m for m in matches if m.kind == "extra"]
    unknowns = [m for m in matches if m.kind == "unknown"]
    forbidden = [m for m in matches if m.kind == "forbidden"]
    misses = [m for m in matches if m.kind == "miss"]

    required_total = sum(1 for i in truth.items if i.required)
    optional_total = len(truth.items) - required_total

    recall = _ratio_or_none(len(required_hits), required_total)
    optional_recall = _ratio_or_none(len(optional_hits), optional_total)
    precision = _ratio_or_none(len(hits), len(hits) + len(extras)) if full else None
    f1 = None
    if precision is not None and recall is not None and (precision + recall) > 0:
        f1 = 2 * precision * recall / (precision + recall)

    q_scored = [m for m in hits if m.quantity_ok is not None]
    u_scored = [m for m in hits if m.unit_ok is not None]
    # A hit is usable when nothing the truth states about it is wrong. A field
    # the truth leaves unstated (None) cannot be wrong.
    usable_required = [
        m for m in required_hits if m.quantity_ok is not False and m.unit_ok is not False
    ]
    scale_errors = sum(
        1 for m in q_scored if m.quantity_ok is False and scale_factor(m.quantity_ratio) is not None
    )

    counts = {
        "hit": len(hits),
        "miss": len(misses),
        "extra": len(extras),
        "unknown": len(unknowns),
        "forbidden": len(forbidden),
        "truth_total": len(truth.items),
        "truth_required": required_total,
        "extracted_total": len(refs),
        "quantity_wrong": sum(1 for m in q_scored if m.quantity_ok is False),
        "scale_errors": scale_errors,
    }
    return DocScore(
        doc_id=truth.doc_id,
        plan_type=truth.plan_type,
        precision=precision,
        recall=recall,
        f1=f1,
        optional_recall=optional_recall,
        quantity_accuracy=_ratio_or_none(sum(1 for m in q_scored if m.quantity_ok), len(q_scored)),
        unit_accuracy=_ratio_or_none(sum(1 for m in u_scored if m.unit_ok), len(u_scored)),
        category_accuracy=_ratio_or_none(sum(1 for m in hits if m.category_ok), len(hits)),
        hallucinations=len(forbidden),
        counts=counts,
        matches=matches,
        usable_recall=_ratio_or_none(len(usable_required), required_total),
    )


def _ratio_or_none(numerator: int, denominator: int) -> Optional[float]:
    """An undefined metric is None. A zero and an unmeasurable are different facts."""
    if denominator <= 0:
        return None
    return numerator / float(denominator)


def aggregate(scores: Sequence[DocScore]) -> dict:
    """Macro-average across documents. A metric no document defined stays None."""
    scores = list(scores or [])
    out = {
        "documents": len(scores),
        "hallucinations": sum(s.hallucinations for s in scores),
        "defined": {},
        "counts": {},
    }
    for key in METRIC_KEYS:
        values = [getattr(s, key) for s in scores]
        values = [v for v in values if v is not None and not math.isnan(v)]
        out[key] = (sum(values) / len(values)) if values else None
        out["defined"][key] = len(values)
    totals: Dict[str, int] = {}
    for s in scores:
        for key, value in (s.counts or {}).items():
            totals[key] = totals.get(key, 0) + int(value)
    out["counts"] = totals
    return out
