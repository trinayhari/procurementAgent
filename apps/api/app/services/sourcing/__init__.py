"""Supplier sourcing: geocode a project, search Google Places per buy-package,
discover supplier emails, and bucket results into distance tiers.

The Google client (``places``) is import-lazy and the orchestrator (``service``)
falls back to a clearly-flagged mock when no API key is set — mirroring the
extraction package — so the whole flow is exercisable offline.
"""
from app.services.sourcing import distance, emails, packages, places, service

__all__ = ["distance", "emails", "packages", "places", "service"]
