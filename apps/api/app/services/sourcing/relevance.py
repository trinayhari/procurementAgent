"""Supplier relevance scoring for Google Places search results.

Cheap heuristics (types, name) run before enrichment; website text + optional
LLM verification run after a single website fetch alongside email discovery.
"""
from __future__ import annotations

import re
from typing import List, NamedTuple, Optional

from app.config import settings
from app.services.sourcing import packages

# Google Places types that indicate consumer retail or unrelated businesses.
_DENY_TYPES = frozenset(
    {
        "home_goods_store",
        "furniture_store",
        "department_store",
        "clothing_store",
        "shoe_store",
        "jewelry_store",
        "electronics_store",
        "book_store",
        "pet_store",
        "florist",
        "beauty_salon",
        "hair_care",
        "spa",
        "gym",
        "restaurant",
        "cafe",
        "bar",
        "bakery",
        "meal_takeaway",
        "meal_delivery",
        "lodging",
        "hotel",
        "motel",
        "movie_theater",
        "night_club",
        "supermarket",
        "grocery_or_supermarket",
        "convenience_store",
        "gas_station",
        "car_dealer",
        "car_repair",
        "car_wash",
        "bank",
        "atm",
        "insurance_agency",
        "real_estate_agency",
        "travel_agency",
        "school",
        "university",
        "hospital",
        "doctor",
        "dentist",
        "pharmacy",
        "veterinary_care",
        "church",
        "place_of_worship",
        "lawyer",
        "accounting",
    }
)

# Types that weakly suggest wholesale/industrial supply (small boost only).
_PREFER_TYPES = frozenset(
    {
        "store",
        "point_of_interest",
        "establishment",
    }
)

# Name fragments that indicate big-box / consumer retail (case-insensitive).
_DENY_NAME_FRAGMENTS = (
    "home depot",
    "lowe's",
    "lowes",
    "walmart",
    "target",
    "costco",
    "sam's club",
    "sams club",
    "menards",
    "ace hardware",
    "true value",
    "dollar general",
    "dollar tree",
    "family dollar",
    "amazon",
    "best buy",
    "michaels",
    "bed bath",
    "ikea",
    "mcdonald",
    "starbucks",
    "subway",
    "walgreens",
    "cvs ",
    "cvs pharmacy",
)

# Name fragments that suggest wholesale / distributor (case-insensitive).
_PREFER_NAME_FRAGMENTS = (
    "supply",
    "distributor",
    "distribution",
    "wholesale",
    "waterworks",
    "precast",
    "fabricat",
    "industrial",
    "materials",
    "masonry",
    "concrete",
    "steel",
    "electrical",
    "lumber",
    "pipe",
    "utility",
)

# Website terms that suggest contractor-facing supply (case-insensitive).
_PREFER_WEBSITE_TERMS = (
    "wholesale",
    "distributor",
    "contractor",
    "commercial",
    "industrial",
    "supply",
    "quote",
    "rfq",
    "bid",
)

_YES_RE = re.compile(r"\byes\b", re.IGNORECASE)
_NO_RE = re.compile(r"\bno\b", re.IGNORECASE)
_CONF_RE = re.compile(r"(?:confidence|score)?\s*:?\s*(0\.\d+|1\.0|1|0)")


class RelevanceScore(NamedTuple):
    score: float
    verified: bool
    reason: str


def passes_prefilter(name: str, types: Optional[List[str]] = None) -> bool:
    """Cheap gate before Place Details / website fetch. True = keep candidate."""
    norm = (name or "").strip().lower()
    if not norm:
        return False
    for frag in _DENY_NAME_FRAGMENTS:
        if frag in norm:
            return False
    place_types = {t.lower() for t in (types or [])}
    if place_types & _DENY_TYPES:
        return False
    return True


def _heuristic_score(
    name: str,
    types: Optional[List[str]],
    website_html: str,
    category_key: str,
) -> tuple[float, str]:
    score = 0.35
    reasons: List[str] = []

    norm = (name or "").strip().lower()
    for frag in _PREFER_NAME_FRAGMENTS:
        if frag in norm:
            score += 0.12
            reasons.append(f"name:{frag}")
            break

    place_types = {t.lower() for t in (types or [])}
    if place_types & _PREFER_TYPES:
        score += 0.05

    html_lower = (website_html or "").lower()
    if html_lower:
        for term in _PREFER_WEBSITE_TERMS:
            if term in html_lower:
                score += 0.08
                reasons.append(f"site:{term}")
                break
        # Category-specific keywords from the package search presets.
        for kw in packages.keywords_for(category_key):
            token = kw.split()[0].lower()
            if len(token) >= 4 and token in html_lower:
                score += 0.1
                reasons.append(f"site:{token}")
                break

    score = min(score, 0.85)
    reason = "heuristic:" + (",".join(reasons) if reasons else "neutral")
    return score, reason


def _llm_verify(
    name: str,
    category_key: str,
    website_html: str,
    verify_hint: Optional[str] = None,
) -> Optional[tuple[bool, float, str]]:
    """Ask the model whether this business serves the category. Best-effort."""
    if not settings.search_verify_with_llm or not settings.openai_api_key:
        return None
    hint = verify_hint or packages.verify_hint_for(category_key)
    snippet = (website_html or "")[:3000]
    try:
        from openai import OpenAI

        client = OpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url or None,
        )
        prompt = (
            "You are vetting suppliers for a construction procurement RFQ.\n"
            f"Business name: {name}\n"
            f"Category: {packages.label_for(category_key)}\n"
            f"Accept if: {hint}\n\n"
            "Website excerpt (may be empty):\n"
            f"{snippet or '(no website content)'}\n\n"
            "Does this business wholesale/distribute the category materials to "
            "construction contractors (NOT a consumer retail store)?\n"
            "Reply on two lines:\n"
            "Line 1: YES or NO\n"
            "Line 2: confidence 0.0-1.0"
        )
        resp = client.chat.completions.create(
            model=settings.openai_vision_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=20,
        )
        answer = (resp.choices[0].message.content or "").strip()
        lines = [ln.strip() for ln in answer.splitlines() if ln.strip()]
        first = lines[0] if lines else answer
        is_yes = bool(_YES_RE.search(first)) and not _NO_RE.match(first)
        is_no = bool(_NO_RE.search(first)) and not _YES_RE.search(first)
        conf = 0.5
        for ln in lines[1:] + [answer]:
            m = _CONF_RE.search(ln)
            if m:
                conf = float(m.group(1))
                if conf > 1.0:
                    conf = conf / 100.0
                break
        if is_no:
            return False, min(conf, 0.4), "llm:no"
        if is_yes:
            return True, conf, "llm:yes"
    except Exception:
        return None
    return None


def score_supplier(
    name: str,
    types: Optional[List[str]],
    website_html: str,
    category_key: str,
    *,
    verify_hint: Optional[str] = None,
) -> RelevanceScore:
    """Score a supplier for category fit. Never raises."""
    if not passes_prefilter(name, types):
        return RelevanceScore(0.0, False, "prefilter:rejected")

    heuristic, h_reason = _heuristic_score(name, types, website_html, category_key)
    llm = _llm_verify(name, category_key, website_html, verify_hint=verify_hint)

    if llm is None:
        final = heuristic
        reason = h_reason
    else:
        is_match, llm_conf, llm_tag = llm
        if is_match:
            final = 0.35 * heuristic + 0.65 * llm_conf
            reason = f"{h_reason};{llm_tag}"
        else:
            final = min(0.35 * heuristic, 0.35)
            reason = f"{h_reason};{llm_tag}"

    final = round(min(max(final, 0.0), 1.0), 2)
    verified = final >= settings.search_relevance_min_score
    return RelevanceScore(final, verified, reason)
