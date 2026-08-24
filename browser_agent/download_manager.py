"""Privacy-aware validation and finalization of expected report downloads."""

from pathlib import Path
import uuid

from browser_agent.errors import DownloadValidationError
from browser_agent.models import DownloadedFile
from utils.file_utils import ensure_temp_directory
from utils.logger import get_logger


logger = get_logger(__name__)
PDF_SIGNATURE = b"%PDF"


class ReportDownloadManager:
    def __init__(self, temp_dir: Path, max_download_mb: int = 25) -> None:
        self._temp_dir = ensure_temp_directory(temp_dir).resolve()
        self._max_bytes = max(1, max_download_mb) * 1024 * 1024

    @property
    def temp_dir(self) -> Path:
        return self._temp_dir

    def staging_path(self) -> Path:
        return self._temp_dir / f"report-download-{uuid.uuid4().hex}.part"

    def validate_pdf(self, staged_path: Path) -> DownloadedFile:
        resolved = staged_path.resolve()
        try:
            if resolved.parent != self._temp_dir or not resolved.is_file():
                raise DownloadValidationError("The expected report file was not created.")
            size = resolved.stat().st_size
            if size <= 0:
                raise DownloadValidationError("The downloaded report is empty.")
            if size > self._max_bytes:
                raise DownloadValidationError("The downloaded report exceeds the size limit.")
            with resolved.open("rb") as handle:
                signature = handle.read(len(PDF_SIGNATURE))
            if signature != PDF_SIGNATURE:
                raise DownloadValidationError(
                    "The downloaded file is not a validated PDF report."
                )

            final_path = self._temp_dir / f"lab_report_{uuid.uuid4().hex}.pdf"
            resolved.replace(final_path)
            logger.info("Controlled report download validated")
            return DownloadedFile(
                path=str(final_path),
                media_type="application/pdf",
                size_bytes=size,
                validation_status="validated",
            )
        except DownloadValidationError:
            self._remove_if_allowed(resolved)
            raise
        except OSError as exc:
            self._remove_if_allowed(resolved)
            raise DownloadValidationError(
                "The downloaded report could not be validated."
            ) from exc

    def _remove_if_allowed(self, path: Path) -> None:
        try:
            if path.parent == self._temp_dir and path.is_file():
                path.unlink()
        except OSError:
            logger.warning("Invalid report download could not be removed")
