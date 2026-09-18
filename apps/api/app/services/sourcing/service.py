"""Supplier search orchestrator.

search_suppliers(loc, category, radius) → list of FoundSupplierResult bucketed by
tier. With no Google key it returns a clearly-flagged mock so the whole flow is
exercisable offline (mirrors extraction/service.py).
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from typing import List, Optional, Tuple

from app.config import settings
from app.services.sourcing import distance, emails, packages, places, relevance

LatLng = Tuple[float, float]


@dataclass
class FoundSupplierResult:
    name: str
    address: str
    distance_miles: float
    tier: int
    contact_name: Optional[str]
    email: Optional[str]
    phone: Optional[str]
    website: Optional[str]
    material_categories: List[str] = field(default_factory=list)
    email_source: str = "none"
    place_id: Optional[str] = None
    relevance_score: float = 1.0
    verify_reason: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def is_configured() -> bool:
    return places.is_configured()


def _place_coords(place: dict) -> Optional[LatLng]:
    try:
        loc = place.get("geometry", {}).get("location", {})
        return float(loc["lat"]), float(loc["lng"])
    except (KeyError, TypeError, ValueError):
        return None


def _prefilter_candidates(
    raw: dict,
    origin: LatLng,
    radius_mi: int,
) -> List[Tuple[str, dict, float]]:
    """Cheap distance + types/name gate before Details / website fetch."""
    survivors: List[Tuple[str, dict, float]] = []
    for pid, place in raw.items():
        coords = _place_coords(place)
        if coords is None:
            continue
        dist = distance.haversine_miles(origin, coords)
        if dist > radius_mi:
            continue
        if distance.tier_for(dist) == 0:
            continue
        name = place.get("name") or ""
        types = place.get("types") or []
        if not relevance.passes_prefilter(name, types):
            continue
        survivors.append((pid, place, dist))

    survivors.sort(key=lambda item: item[2])
    cap = settings.search_candidate_pool
    if cap > 0:
        survivors = survivors[:cap]
    return survivors


def search_suppliers(
    project_loc: str,
    category_key: str,
    radius_mi: int,
    cached_latlng: Optional[LatLng] = None,
    keywords: Optional[List[str]] = None,
    label: Optional[str] = None,
    verify_hint: Optional[str] = None,
) -> Tuple[List[FoundSupplierResult], Optional[LatLng], bool]:
    """Return (results, latlng_used, mocked).

    results are sorted by relevance then distance and capped at
    search_max_results_per_package. latlng_used is returned so the caller can
    cache the project geocode.

    ``keywords``/``label`` override the buy-package presets — this is how an
    ad-hoc RFQ searches on a free-text description instead of a fixed package.
    ``verify_hint`` overrides the relevance-verification hint (used by trade/
    subcontractor searches, which want installers rather than distributors).
    """
    ad_hoc = keywords is not None
    if not places.is_configured():
        if ad_hoc:
            return _mock_adhoc_suppliers(label or category_key, radius_mi), None, True
        return _mock_suppliers(category_key, radius_mi), None, True

    # 1. Geocode (or reuse cached project coordinates).
    origin = cached_latlng
    if origin is None:
        origin = places.geocode(project_loc)

    radius_m = int(min(radius_mi, settings.search_tier3_max_mi) * 1609.34)
    label = label or packages.label_for(category_key)
    search_keywords = keywords if ad_hoc else packages.keywords_for(category_key)
    if verify_hint is None:
        verify_hint = (
            f"Wholesale distributor or supplier of {label} materials to contractors — "
            "not a consumer retail store."
            if ad_hoc
            else packages.verify_hint_for(category_key)
        )

    # 2. Text Search across the keywords; dedupe by place_id.
    raw: dict = {}
    for keyword in search_keywords:
        for place in places.text_search(f"{keyword} {project_loc}", origin[0], origin[1], radius_m):
            pid = place.get("place_id")
            if pid and pid not in raw:
                raw[pid] = place

    # 3. Cheap pre-filter + candidate pool cap.
    candidates = _prefilter_candidates(raw, origin, radius_mi)

    # 4. Details + single website fetch + relevance scoring, concurrently.
    def _enrich(item: Tuple[str, dict, float]) -> Optional[FoundSupplierResult]:
        pid, place, dist = item
        tier = distance.tier_for(dist)
        if tier == 0:
            return None

        detail = {}
        try:
            detail = places.place_details(pid)
        except places.PlacesUnavailable:
            detail = {}

        name = detail.get("name") or place.get("name") or "Unknown supplier"
        types = detail.get("types") or place.get("types") or []
        if not relevance.passes_prefilter(name, types):
            return None

        website = places.website_for(detail)
        html_pages = emails.fetch_website_pages(website) if website else []
        website_html = "\n".join(html_pages)

        rel = relevance.score_supplier(
            name,
            types,
            website_html,
            category_key,
            verify_hint=verify_hint,
        )
        if not rel.verified:
            return None

        disc = emails.discover_email(website, name, html_pages=html_pages or None)
        return FoundSupplierResult(
            name=name,
            address=detail.get("formatted_address") or place.get("formatted_address") or "",
            distance_miles=round(dist, 1),
            tier=tier,
            contact_name=None,
            email=disc.email,
            phone=detail.get("formatted_phone_number"),
            website=website,
            material_categories=[label],
            email_source=disc.source,
            place_id=pid,
            relevance_score=rel.score,
            verify_reason=rel.reason,
        )

    results: List[FoundSupplierResult] = []
    if candidates:
        with ThreadPoolExecutor(max_workers=settings.search_max_workers) as pool:
            for res in pool.map(_enrich, candidates):
                if res is not None:
                    results.append(res)

    results.sort(key=lambda r: (-r.relevance_score, r.distance_miles))
    return results[: settings.search_max_results_per_package], origin, False


# --------------------------------------------------------------------- mock
# Plausible suppliers spread across tiers, so the UI is fully exercisable with no
# Google key. Modeled loosely on real waterworks/precast distributors.
_MOCK = {
    "water": [
        ("Core & Main", 12.0, "sales@coreandmain.com"),
        ("Ferguson Waterworks", 18.0, "quotes@ferguson.com"),
        ("HD Supply Waterworks", 41.0, "priya.anand@hdsupply.com"),
        ("Mayer Supply", 63.0, None),
        ("National Waterworks Mfg", 134.0, "estimating@nationalww.com"),
    ],
    "sewer": [
        ("Core & Main", 12.0, "sales@coreandmain.com"),
        ("Fortiline Waterworks", 22.0, "lromero@fortiline.com"),
        ("Regional Precast Co.", 48.0, "sales@regionalprecast.com"),
        ("County Precast Manufacturing", 88.0, None),
    ],
    "storm": [
        ("Oldcastle Infrastructure", 16.0, "bids@oldcastle.com"),
        ("County Materials", 39.0, "sales@countymaterials.com"),
        ("Forterra Pipe & Precast", 67.0, "quotes@forterra.com"),
        ("Regional RCP Plant", 142.0, None),
    ],
    "erosion": [
        ("Sitework Supply Co.", 9.0, "sales@siteworksupply.com"),
        ("Geotextile Distributors Inc.", 28.0, "info@geotextiledist.com"),
        ("Landscape Supply Yard", 54.0, None),
    ],
}


# Category-agnostic mock used for ad-hoc searches (any free-text description),
# so the select → generate flow is exercisable offline without a Google key.
_MOCK_ADHOC = [
    ("Regional Building Supply", 11.0, "sales@regionalbuilding.example.com"),
    ("Metro Materials Co.", 27.0, "quotes@metromaterials.example.com"),
    ("Statewide Industrial Supply", 52.0, "estimating@statewideind.example.com"),
    ("National Manufacturing Group", 121.0, None),
]


def _mock_adhoc_suppliers(label: str, radius_mi: int) -> List[FoundSupplierResult]:
    out: List[FoundSupplierResult] = []
    for i, (name, dist, email) in enumerate(_MOCK_ADHOC):
        if dist > radius_mi:
            continue
        tier = distance.tier_for(dist)
        if tier == 0:
            continue
        slug = name.lower().split()[0]
        out.append(
            FoundSupplierResult(
                name=name,
                address=f"{200 + i * 30} Commerce Dr",
                distance_miles=dist,
                tier=tier,
                contact_name=None,
                email=email,
                phone=f"(555) 555-0{200 + i:03d}",
                website=f"https://{slug}.example.com",
                material_categories=[label] if label else [],
                email_source="mock" if email else "none",
                place_id=f"mock-adhoc-{i}",
                relevance_score=1.0,
                verify_reason="mock",
            )
        )
    out.sort(key=lambda r: (-r.relevance_score, r.distance_miles))
    return out


def _mock_suppliers(category_key: str, radius_mi: int) -> List[FoundSupplierResult]:
    label = packages.label_for(category_key)
    out: List[FoundSupplierResult] = []
    for i, (name, dist, email) in enumerate(_MOCK.get(category_key, [])):
        if dist > radius_mi:
            continue
        tier = distance.tier_for(dist)
        if tier == 0:
            continue
        slug = name.lower().split()[0]
        out.append(
            FoundSupplierResult(
                name=name,
                address=f"{100 + i * 25} Industrial Pkwy",
                distance_miles=dist,
                tier=tier,
                contact_name=None,
                email=email,
                phone=f"(555) 555-0{100 + i:03d}",
                website=f"https://{slug}.example.com",
                material_categories=[label],
                email_source="mock" if email else "none",
                place_id=f"mock-{category_key}-{i}",
                relevance_score=1.0,
                verify_reason="mock",
            )
        )
    out.sort(key=lambda r: (-r.relevance_score, r.distance_miles))
    return out
