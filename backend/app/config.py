from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, overridable via environment variables or a .env file."""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="PROCUREAI_", extra="ignore")

    app_name: str = "ProcureAI API"
    # Origins allowed to call the API from the browser (the Vite dev server by default).
    cors_origins: List[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    # ------------------------------------------------------------- persistence
    # SQLAlchemy connection URL. Defaults to a SQLite file in the backend dir;
    # override with PROCUREAI_DATABASE_URL (e.g. a Postgres DSN) in production.
    database_url: str = "sqlite:///./procureai.db"

    # ----------------------------------------------------------- file uploads
    # Where uploaded plan sets are stored on disk (created on first upload).
    upload_dir: str = "uploads"
    max_upload_mb: int = 500

    # ------------------------------------------------ GPT-4.1 vision extraction
    # Leave the key empty to run a clearly-flagged mock extraction (no API calls).
    openai_api_key: str = ""
    # Optional OpenAI-compatible gateway (e.g. OpenRouter: https://openrouter.ai/api/v1).
    # Empty → official OpenAI endpoint.
    openai_base_url: str = ""
    openai_vision_model: str = "gpt-4.1"
    # Page rasterisation + request limits (cost/detail trade-offs — see pdf.py).
    vision_dpi: int = 150
    vision_max_pages: int = 30
    vision_image_detail: str = "high"  # "high" | "low" | "auto"
    vision_max_tokens: int = 8000
    # Per-sheet extraction runs in parallel; cap concurrent vision calls.
    vision_max_workers: int = 5
    # Tiling — large plan sheets (24x36) lose small callout text when sent as one
    # downscaled image, so each sheet is rendered as a grid of high-DPI tiles. Set
    # cols=rows=1 to disable tiling.
    vision_tile_cols: int = 3
    vision_tile_rows: int = 2
    vision_tile_dpi: int = 200
    vision_tile_overlap: float = 0.08

    # ------------------------------------------------ Google Maps Platform
    # Geocoding (project loc → lat/lng) + Places Text Search/Details (supplier
    # discovery). Leave empty to run a clearly-flagged mock supplier search.
    google_maps_api_key: str = ""

    # ------------------------------------------- Gmail (single-user OAuth2 send)
    # Mint the refresh token once out-of-band (InstalledAppFlow, scope
    # gmail.send) and paste it here. Empty creds → mock sender (logs only).
    gmail_client_id: str = ""
    gmail_client_secret: str = ""
    gmail_refresh_token: str = ""
    gmail_sender_address: str = ""  # the "From" address, e.g. you@gmail.com

    # ------------------------------------------------ supplier search tuning
    # Tier bounds (miles) for bucketing results; the UI radius slider re-buckets.
    search_default_radius_mi: int = 75
    search_tier1_max_mi: int = 25   # Tier 1: local
    search_tier2_max_mi: int = 75   # Tier 2: regional branches
    search_tier3_max_mi: int = 250  # Tier 3: manufacturers / large distributors
    search_max_results_per_package: int = 20
    # Per-supplier website fetch for email discovery (best-effort).
    search_email_fetch_timeout_s: int = 8
    search_max_workers: int = 6  # cap concurrent details + website fetches


settings = Settings()
