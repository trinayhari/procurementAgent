from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, overridable via environment variables or a .env file."""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="PROCUREAI_", extra="ignore")

    app_name: str = "Proq API"
    # "development" or "production". Production refuses to boot with the default
    # JWT secret and warns when CORS is still localhost-only (see main.py).
    env: str = "development"
    # Origins allowed to call the API from the browser (the Vite dev server by default).
    cors_origins: List[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
    ]

    # ------------------------------------------------------------- persistence
    # SQLAlchemy connection URL. Defaults to a SQLite file in the backend dir;
    # override with PROCUREAI_DATABASE_URL (e.g. a Postgres DSN) in production.
    database_url: str = "sqlite:///./procureai.db"

    # Seed the prototype/demo dataset (sample projects, suppliers, quotes,
    # dashboard metrics, timeline, etc.) on startup. OFF by default so the app
    # only ever shows real, user-generated data; set PROCUREAI_SEED_DEMO_DATA=true
    # for a populated demo environment.
    seed_demo_data: bool = False

    # ----------------------------------------------------------------- auth
    # Secret used to sign JWT access tokens. CHANGE THIS in production via
    # PROCUREAI_JWT_SECRET — the default is only safe for local development.
    jwt_secret: str = "dev-insecure-change-me"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60 * 24 * 7  # one week

    # ----------------------------------------------------------- file uploads
    # Where uploaded plan sets are stored on disk (created on first upload).
    upload_dir: str = "uploads"
    max_upload_mb: int = 500

    # -------------------------------------------------------- object storage
    # "local" (default): files under upload_dir — simple, but ephemeral on
    # hosts without a persistent disk. "s3": any S3-compatible store (AWS S3,
    # Cloudflare R2, MinIO) — uploads survive redeploys; serving uses
    # presigned URLs. Previously stored local files keep working after a
    # switch (the backend is chosen per file locator).
    storage_backend: str = "local"
    s3_bucket: str = ""
    s3_region: str = ""
    s3_endpoint_url: str = ""  # set for R2/MinIO; empty for AWS S3
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    s3_prefix: str = "uploads"
    s3_presign_expiry_s: int = 300

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
    # Per-sheet extraction runs in parallel; cap concurrent vision calls. Each
    # in-flight sheet holds its rendered tiles in memory, so this directly bounds
    # peak RAM — kept low (2) so large plan sets don't OOM the container.
    vision_max_workers: int = 2
    # Tiling — large plan sheets (24x36) lose small callout text when sent as one
    # downscaled image, so each sheet is rendered as a grid of high-DPI tiles. Set
    # cols=rows=1 to disable tiling.
    vision_tile_cols: int = 3
    vision_tile_rows: int = 2
    # Render DPI for tiles. 150 reads callouts on 24x36 sheets fine while using
    # ~40% less memory than 200 (a single large sheet at 200 DPI spikes ~325MB);
    # the tile grid already recovers small-text legibility.
    vision_tile_dpi: int = 150
    vision_tile_overlap: float = 0.08
    # Denser tile grid for TARGETED vision passes (text-pass escalation and
    # category top-up read only a few matched sheets, so the extra tiles are
    # affordable). Small plan symbols — receptacles, fixtures, switches — blur
    # at the standard grid on 48x36 sheets; the dense grid keeps them countable.
    vision_dense_tile_cols: int = 4
    vision_dense_tile_rows: int = 3
    # Text-first escape hatch: when the one-shot text pass returns fewer items
    # than this, the text layer clearly didn't carry the discipline's content
    # (symbols, not text — e.g. electrical devices on MEP sheets), so the
    # pipeline escalates to the per-sheet vision path on the relevant sheets.
    text_pass_min_items: int = 3

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
    # How far back the quote-ingest poller looks for supplier replies.
    quote_ingest_lookback_days: int = 30

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
    # Relevance filtering: cap candidates before enrichment, drop below min score.
    search_candidate_pool: int = 40
    search_relevance_min_score: float = 0.5
    search_verify_with_llm: bool = True


settings = Settings()
