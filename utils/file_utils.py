"""Safe temporary-file handling for uploaded documents and result files."""

from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
import uuid

from PIL import Image, UnidentifiedImageError

from utils.logger import get_logger


logger = get_logger(__name__)
SUPPORTED_FORMATS = {"JPEG": ".jpg", "PNG": ".png"}
SUPPORTED_SUFFIXES = {".jpg", ".jpeg", ".png"}


class UploadValidationError(ValueError):
    """Base class for errors that are safe to present to a user."""


class UnsupportedImageError(UploadValidationError):
    pass


class InvalidImageError(UploadValidationError):
    pass


class ImageTooLargeError(UploadValidationError):
    pass


def ensure_temp_directory(temp_dir: Path) -> Path:
    temp_dir.mkdir(parents=True, exist_ok=True)
    return temp_dir


def save_uploaded_image(
    file_data: bytes,
    original_name: str,
    temp_dir: Path,
    max_upload_mb: int,
) -> Path:
    """Validate and store an image under a generated name.

    Original filenames and document content are deliberately never logged.
    """
    if not file_data:
        raise InvalidImageError("The uploaded file is empty.")

    if Path(original_name).suffix.lower() not in SUPPORTED_SUFFIXES:
        raise UnsupportedImageError("Unsupported filename extension.")

    if len(file_data) > max_upload_mb * 1024 * 1024:
        raise ImageTooLargeError("The uploaded file exceeds the configured limit.")

    try:
        with Image.open(BytesIO(file_data)) as image:
            image_format = image.format
            image.verify()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise InvalidImageError("The uploaded image could not be decoded.") from exc

    if image_format not in SUPPORTED_FORMATS:
        raise UnsupportedImageError("Unsupported decoded image format.")

    ensure_temp_directory(temp_dir)
    output_path = temp_dir / f"upload-{uuid.uuid4().hex}{SUPPORTED_FORMATS[image_format]}"
    output_path.write_bytes(file_data)
    logger.info("Validated image saved to temporary storage")
    return output_path


def remove_files(paths: list[Path | None], allowed_directory: Path) -> None:
    allowed_directory = allowed_directory.resolve()
    for path in paths:
        if path is None:
            continue
        try:
            resolved = path.resolve()
            if resolved.parent == allowed_directory and resolved.is_file():
                resolved.unlink()
                logger.info("Temporary run file removed")
        except OSError:
            logger.exception("Could not remove a temporary run file")


def cleanup_stale_files(temp_dir: Path, max_age_hours: int = 24) -> int:
    """Remove stale files created by this app; never recurse outside temp_dir."""
    if not temp_dir.exists():
        return 0

    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    removed = 0
    for path in temp_dir.iterdir():
        if not path.is_file() or path.name == ".gitkeep":
            continue
        try:
            modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            if modified < cutoff:
                path.unlink()
                removed += 1
        except OSError:
            logger.exception("Could not inspect or remove a stale temporary file")
    if removed:
        logger.info("Removed %s stale temporary file(s)", removed)
    return removed
