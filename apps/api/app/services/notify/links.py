"""Absolute links into the web app for notices (approval page, project views).

Same base-URL rule as the invite email: PROCUREAI_APP_BASE_URL when set,
else the first CORS origin, else a relative hash link.
"""
from app.config import settings


def app_url(hash_path: str) -> str:
    """`hash_path` is the part after the origin, e.g. "/#/approve/<token>"."""
    base = settings.app_base_url or (settings.cors_origins[0] if settings.cors_origins else "")
    base = base.rstrip("/")
    return f"{base}{hash_path}" if base else hash_path


def project_url(project_id: str) -> str:
    return app_url(f"/#/project/{project_id}")


def comparison_url(project_id: str, package: str) -> str:
    return app_url(f"/#/project/{project_id}/quotes/compare/{package}")


def approve_url(token: str) -> str:
    return app_url(f"/#/approve/{token}")
