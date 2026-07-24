"""Pure distance + tier helpers (no I/O — unit-testable).

Distances are straight-line (haversine), not driving distance — good enough for
tier bucketing and avoids the cost/quota of the Distance Matrix API. Surface it
as "approx." in the UI.
"""
import math
from typing import Tuple

from app.config import settings

LatLng = Tuple[float, float]

_EARTH_RADIUS_MI = 3958.7613


def haversine_miles(a: LatLng, b: LatLng) -> float:
    """Great-circle distance between two (lat, lng) points, in miles."""
    lat1, lng1 = a
    lat2, lng2 = b
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lng2 - lng1)
    h = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * _EARTH_RADIUS_MI * math.asin(min(1.0, math.sqrt(h)))


def tier_for(distance_mi: float) -> int:
    """Bucket a distance into a tier. 0 means out of the configured Tier 3 range.

    Tier 1: local            (<= search_tier1_max_mi, default 25)
    Tier 2: regional         (<= search_tier2_max_mi, default 75)
    Tier 3: manufacturers    (<= search_tier3_max_mi, default 250)
    """
    if distance_mi <= settings.search_tier1_max_mi:
        return 1
    if distance_mi <= settings.search_tier2_max_mi:
        return 2
    if distance_mi <= settings.search_tier3_max_mi:
        return 3
    return 0


def tier_label(tier: int) -> str:
    if tier == 1:
        return f"Local · 0–{settings.search_tier1_max_mi} mi"
    if tier == 2:
        return f"Regional · {settings.search_tier1_max_mi}–{settings.search_tier2_max_mi} mi"
    if tier == 3:
        return f"Manufacturers · {settings.search_tier2_max_mi}–{settings.search_tier3_max_mi} mi"
    return "Out of range"
