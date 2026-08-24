"""Streamlit entry point through controlled Phase 4 webpage observation."""

from config.settings import get_settings
from ui.main_page import render_app
from utils.file_utils import cleanup_stale_files, ensure_temp_directory
from utils.logger import configure_logging, get_logger


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    logger = get_logger(__name__)

    temp_dir = ensure_temp_directory(settings.temp_dir)
    cleanup_stale_files(temp_dir, settings.temp_file_max_age_hours)
    logger.info("Application started")

    render_app(settings)


if __name__ == "__main__":
    main()
