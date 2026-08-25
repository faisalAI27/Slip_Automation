"""Shared validation for already-downloaded report artifacts."""

from dataclasses import dataclass
from pathlib import Path


SUPPORTED_REPORT_TYPES = {
    "application/pdf": (b"%PDF", ".pdf"),
    "image/png": (b"\x89PNG\r\n\x1a\n", ".png"),
    "image/jpeg": (b"\xff\xd8\xff", ".jpg"),
    "application/zip": (b"PK\x03\x04", ".zip"),
}


@dataclass(frozen=True, slots=True)
class ValidatedReport:
    path: Path
    content_type: str
    size_bytes: int
    extension: str


def validate_report_path(
    path: Path,
    *,
    allowed_directory: Path,
    max_download_mb: int,
    expected_content_type: str | None = None,
) -> ValidatedReport | None:
    """Validate an owned report by parent directory, size, and file signature."""
    resolved = path.resolve()
    allowed = allowed_directory.resolve()
    try:
        if resolved.parent != allowed or not resolved.is_file():
            return None
        size = resolved.stat().st_size
        if size <= 0 or size > max(1, max_download_mb) * 1024 * 1024:
            return None
        signature = resolved.read_bytes()[:8]
    except OSError:
        return None

    for content_type, (prefix, extension) in SUPPORTED_REPORT_TYPES.items():
        if signature.startswith(prefix):
            if expected_content_type and content_type != expected_content_type:
                return None
            return ValidatedReport(
                path=resolved,
                content_type=content_type,
                size_bytes=size,
                extension=extension,
            )
    return None
