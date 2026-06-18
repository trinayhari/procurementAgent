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


settings = Settings()
