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
    mock_stage_delay_seconds: float
    log_level: str


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    raw_temp_dir = Path(os.getenv("TEMP_DIR", "temp"))
    temp_dir = raw_temp_dir if raw_temp_dir.is_absolute() else PROJECT_ROOT / raw_temp_dir

    return Settings(
        app_env=os.getenv("APP_ENV", "development"),
        debug_mode=_as_bool(os.getenv("DEBUG_MODE"), default=False),
        temp_dir=temp_dir.resolve(),
        temp_file_max_age_hours=int(os.getenv("TEMP_FILE_MAX_AGE_HOURS", "24")),
        max_upload_mb=int(os.getenv("MAX_UPLOAD_MB", "12")),
        mock_stage_delay_seconds=float(os.getenv("MOCK_STAGE_DELAY_SECONDS", "0.65")),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
    )
