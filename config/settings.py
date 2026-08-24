"""Centralized environment-backed application settings."""

from dataclasses import dataclass
from functools import lru_cache
import os
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class Settings:
    app_env: str
    debug_mode: bool
    temp_dir: Path
    temp_file_max_age_hours: int
    max_upload_mb: int
    document_ai_provider: str
    document_ai_model: str
    document_ai_api_key: str | None
    document_ai_timeout_seconds: float
    ollama_base_url: str
    ollama_timeout_seconds: float
    browser_headless: bool
    browser_timeout_seconds: float
    browser_navigation_timeout_seconds: float
    browser_max_search_results: int
    log_level: str


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    raw_temp_dir = Path(os.getenv("TEMP_DIR", "temp"))
    temp_dir = raw_temp_dir if raw_temp_dir.is_absolute() else PROJECT_ROOT / raw_temp_dir
    document_api_key = (os.getenv("DOCUMENT_AI_API_KEY") or "").strip() or None

    return Settings(
        app_env=os.getenv("APP_ENV", "development"),
        debug_mode=_as_bool(os.getenv("DEBUG_MODE"), default=False),
        temp_dir=temp_dir.resolve(),
        temp_file_max_age_hours=int(os.getenv("TEMP_FILE_MAX_AGE_HOURS", "24")),
        max_upload_mb=int(os.getenv("MAX_UPLOAD_MB", "12")),
        document_ai_provider=os.getenv("DOCUMENT_AI_PROVIDER", "ollama").strip(),
        document_ai_model=os.getenv(
            "DOCUMENT_AI_MODEL", "qwen3-vl:4b-instruct"
        ).strip(),
        document_ai_api_key=document_api_key,
        document_ai_timeout_seconds=float(
            os.getenv("DOCUMENT_AI_TIMEOUT_SECONDS", "90")
        ),
        ollama_base_url=os.getenv(
            "OLLAMA_BASE_URL", "http://127.0.0.1:11434"
        ).strip(),
        ollama_timeout_seconds=float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "420")),
        browser_headless=_as_bool(os.getenv("BROWSER_HEADLESS"), default=True),
        browser_timeout_seconds=max(
            1.0, float(os.getenv("BROWSER_TIMEOUT_SECONDS", "30"))
        ),
        browser_navigation_timeout_seconds=max(
            1.0, float(os.getenv("BROWSER_NAVIGATION_TIMEOUT_SECONDS", "45"))
        ),
        browser_max_search_results=max(
            1, min(10, int(os.getenv("BROWSER_MAX_SEARCH_RESULTS", "8")))
        ),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
    )
