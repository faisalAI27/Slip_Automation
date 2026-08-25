"""Privacy-aware validation and finalization of expected report downloads."""

from pathlib import Path
import uuid
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile

from browser_agent.errors import DownloadValidationError
from browser_agent.models import DownloadedFile, DownloadedReportFile
from utils.file_utils import ensure_temp_directory
from utils.logger import get_logger


logger = get_logger(__name__)
PDF_SIGNATURE = b"%PDF"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
JPEG_SIGNATURE = b"\xff\xd8\xff"
ZIP_SIGNATURE = b"PK\x03\x04"


class ReportDownloadManager:
    def __init__(self, temp_dir: Path, max_download_mb: int = 25) -> None:
        self._temp_dir = ensure_temp_directory(temp_dir).resolve()
        self._max_bytes = max(1, max_download_mb) * 1024 * 1024

    @property
    def temp_dir(self) -> Path:
        return self._temp_dir

    @property
    def max_bytes(self) -> int:
        return self._max_bytes

    def staging_path(self) -> Path:
        return self._temp_dir / f"report-download-{uuid.uuid4().hex}.part"

    def validate_pdf(self, staged_path: Path) -> DownloadedFile:
        result = self.validate_report(staged_path)
        if result.media_type != "application/pdf":
            self._remove_if_allowed(Path(result.path))
            raise DownloadValidationError(
                "The downloaded file is not a validated PDF report."
            )
        return result

    def validate_report(self, staged_path: Path) -> DownloadedFile:
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
                signature = handle.read(len(PNG_SIGNATURE))
            if signature.startswith(PDF_SIGNATURE):
                extension = "pdf"
                media_type = "application/pdf"
            elif signature.startswith(PNG_SIGNATURE):
                extension = "png"
                media_type = "image/png"
            elif signature.startswith(JPEG_SIGNATURE):
                extension = "jpg"
                media_type = "image/jpeg"
            else:
                raise DownloadValidationError(
                    "The downloaded file is not a validated PDF or image report."
                )

            final_path = self._temp_dir / f"lab_report_{uuid.uuid4().hex}.{extension}"
            resolved.replace(final_path)
            logger.info("Controlled report download validated")
            return DownloadedFile(
                path=str(final_path),
                media_type=media_type,
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

    def bundle_reports(self, reports: list[DownloadedFile]) -> DownloadedFile:
        if not reports:
            raise DownloadValidationError("No validated reports were available to bundle.")
        if len(reports) == 1:
            return reports[0]

        report_paths = [Path(item.path).resolve() for item in reports]
        if any(
            path.parent != self._temp_dir or not path.is_file()
            for path in report_paths
        ):
            raise DownloadValidationError(
                "A validated report was no longer available for bundling."
            )
        if sum(path.stat().st_size for path in report_paths) > self._max_bytes:
            raise DownloadValidationError(
                "The combined reports exceed the configured download size limit."
            )

        bundle_path = self._temp_dir / f"lab_reports_{uuid.uuid4().hex}.zip"
        try:
            with ZipFile(bundle_path, "w", compression=ZIP_DEFLATED) as archive:
                for index, path in enumerate(report_paths, 1):
                    suffix = path.suffix.casefold()
                    if suffix not in {".pdf", ".png", ".jpg", ".jpeg"}:
                        raise DownloadValidationError(
                            "A report has an unsupported bundled file type."
                        )
                    archive.write(path, arcname=f"latest_report_{index}{suffix}")
            size = bundle_path.stat().st_size
            if size <= 0 or size > self._max_bytes:
                raise DownloadValidationError(
                    "The combined report download is empty or exceeds the size limit."
                )
            with bundle_path.open("rb") as handle:
                if not handle.read(len(ZIP_SIGNATURE)).startswith(ZIP_SIGNATURE):
                    raise DownloadValidationError(
                        "The combined report download is not a valid ZIP archive."
                    )
            with ZipFile(bundle_path) as archive:
                if archive.testzip() is not None:
                    raise DownloadValidationError(
                        "The combined report download contains a damaged file."
                    )
            logger.info("Controlled report bundle validated")
            return DownloadedFile(
                path=str(bundle_path),
                media_type="application/zip",
                size_bytes=size,
                validation_status="validated",
                report_count=len(reports),
                individual_reports=[
                    DownloadedReportFile(
                        path=item.path,
                        media_type=item.media_type,
                        size_bytes=item.size_bytes,
                        validation_status=item.validation_status,
                        display_name=item.display_name,
                    )
                    for item in reports
                ],
            )
        except DownloadValidationError:
            self._remove_if_allowed(bundle_path)
            raise
        except (BadZipFile, OSError) as exc:
            self._remove_if_allowed(bundle_path)
            raise DownloadValidationError(
                "The combined reports could not be bundled safely."
            ) from exc

    def _remove_if_allowed(self, path: Path) -> None:
        try:
            if path.parent == self._temp_dir and path.is_file():
                path.unlink()
        except OSError:
            logger.warning("Invalid report download could not be removed")
