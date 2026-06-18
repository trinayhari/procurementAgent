"""Google Maps Platform client: Geocoding + Places Text Search + Place Details.

All HTTP is confined to this module. ``httpx`` is imported lazily and any missing
key/dependency raises ``PlacesUnavailable`` so the orchestrator can fall back to
its mock path — mirroring extraction/vision.py.
"""
from typing import List, Optional, Tuple

from app.config import settings

LatLng = Tuple[float, float]

_GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
_TEXTSEARCH_URL = "https://maps.googleapis.com/maps/api/place/textsearch/json"
_DETAILS_URL = "https://maps.googleapis.com/maps/api/place/details/json"


class PlacesUnavailable(Exception):
    """Raised when Google Places cannot be called (no key / SDK / API error)."""


def is_configured() -> bool:
    return bool(settings.google_maps_api_key)


def _client():
    if not settings.google_maps_api_key:
        raise PlacesUnavailable("GOOGLE_MAPS_API_KEY is not set")
    try:
        import httpx
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise PlacesUnavailable("httpx package is not installed") from exc
    return httpx.Client(timeout=15.0)


def _get(client, url: str, params: dict) -> dict:
    params = {**params, "key": settings.google_maps_api_key}
    try:
        resp = client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:  # network / HTTP / decode
        raise PlacesUnavailable(f"Google request failed: {exc}") from exc
    status = data.get("status")
    # ZERO_RESULTS is a valid empty answer, not an error.
    if status not in ("OK", "ZERO_RESULTS"):
        msg = data.get("error_message", status)
        raise PlacesUnavailable(f"Google API status {status}: {msg}")
    return data


def geocode(loc: str) -> LatLng:
    """Freeform location string → (lat, lng). Raises PlacesUnavailable on failure."""
    with _client() as client:
        data = _get(client, _GEOCODE_URL, {"address": loc})
    results = data.get("results") or []
    if not results:
        raise PlacesUnavailable(f"No geocode result for {loc!r}")
    geo = results[0]["geometry"]["location"]
    return float(geo["lat"]), float(geo["lng"])


def text_search(keyword: str, lat: float, lng: float, radius_m: int) -> List[dict]:
    """Places Text Search biased to (lat,lng). Returns the first page of results."""
    with _client() as client:
        data = _get(
            client,
            _TEXTSEARCH_URL,
            {
                "query": keyword,
                "location": f"{lat},{lng}",
                "radius": radius_m,
            },
        )
    return data.get("results") or []


def place_details(place_id: str) -> dict:
    """Place Details: website, formatted_phone_number, formatted_address, name."""
    with _client() as client:
        data = _get(
            client,
            _DETAILS_URL,
            {
                "place_id": place_id,
                "fields": "name,formatted_address,formatted_phone_number,website,url",
            },
        )
    return data.get("result") or {}


def website_for(detail: dict) -> Optional[str]:
    return detail.get("website") or None
