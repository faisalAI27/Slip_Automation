from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from browser_agent.download_manager import ReportDownloadManager
from browser_agent.errors import DownloadValidationError


class DownloadManagerTests(unittest.TestCase):
    def test_valid_pdf_gets_generated_safe_name(self) -> None:
        with TemporaryDirectory() as directory:
            manager = ReportDownloadManager(Path(directory), max_download_mb=1)
            staged = manager.staging_path()
            staged.write_bytes(b"%PDF-1.7\nvalidated report")

            result = manager.validate_pdf(staged)

            final = Path(result.path)
            self.assertTrue(final.exists())
            self.assertTrue(final.name.startswith("lab_report_"))
            self.assertNotIn("patient", final.name.casefold())
            self.assertFalse(staged.exists())

    def test_fake_pdf_is_rejected_and_deleted(self) -> None:
        with TemporaryDirectory() as directory:
            manager = ReportDownloadManager(Path(directory), max_download_mb=1)
            staged = manager.staging_path()
            staged.write_bytes(b"<html>not a report</html>")

            with self.assertRaises(DownloadValidationError):
                manager.validate_pdf(staged)

            self.assertFalse(staged.exists())

    def test_oversized_pdf_is_rejected_and_deleted(self) -> None:
        with TemporaryDirectory() as directory:
            manager = ReportDownloadManager(Path(directory), max_download_mb=1)
            staged = manager.staging_path()
            staged.write_bytes(b"%PDF" + b"x" * (1024 * 1024 + 1))

            with self.assertRaises(DownloadValidationError):
                manager.validate_pdf(staged)

            self.assertFalse(staged.exists())

    def test_png_report_is_validated_with_safe_name_and_media_type(self) -> None:
        with TemporaryDirectory() as directory:
            manager = ReportDownloadManager(Path(directory), max_download_mb=1)
            staged = manager.staging_path()
            staged.write_bytes(b"\x89PNG\r\n\x1a\nsynthetic report")

            result = manager.validate_report(staged)

            final = Path(result.path)
            self.assertTrue(final.exists())
            self.assertEqual(final.suffix, ".png")
            self.assertEqual(result.media_type, "image/png")

    def test_jpeg_report_is_validated_with_safe_name_and_media_type(self) -> None:
        with TemporaryDirectory() as directory:
            manager = ReportDownloadManager(Path(directory), max_download_mb=1)
            staged = manager.staging_path()
            staged.write_bytes(b"\xff\xd8\xffsynthetic report")

            result = manager.validate_report(staged)

            final = Path(result.path)
            self.assertTrue(final.exists())
            self.assertEqual(final.suffix, ".jpg")
            self.assertEqual(result.media_type, "image/jpeg")


if __name__ == "__main__":
    unittest.main()
