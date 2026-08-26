import os
import unittest
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

from backend.dependencies import (
    get_backend_settings,
    get_report_retrieval_service,
    get_result_store,
)
from backend.jobs import LocalJobStore
from backend.main import create_app
from config.settings import get_settings
from services.models import (
    ReportRetrievalOutcome,
    RetrievalOutcomeStatus,
    RetrievedReport,
)


def _png_bytes() -> bytes:
    output = BytesIO()
    Image.new("RGB", (12, 9), color="white").save(output, format="PNG")
    return output.getvalue()


class StaticService:
    def __init__(self, outcome: ReportRetrievalOutcome) -> None:
        self.outcome = outcome
        self.calls = 0

    def retrieve(self, image_path: Path, progress_callback=None):
        del image_path, progress_callback
        self.calls += 1
        return self.outcome


class RaisingService:
    def retrieve(self, image_path: Path, progress_callback=None):
        del image_path, progress_callback
        raise RuntimeError("PATIENT-9988 SECRET-CREDENTIAL /private/report/path")


class CloudRunSynchronousApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.temp_dir = Path(self.directory.name)
        self.settings = replace(
            get_settings(),
            app_env="development",
            temp_dir=self.temp_dir,
            max_upload_mb=1,
            max_report_download_mb=1,
            backend_execution_mode="synchronous",
            job_ttl_minutes=30,
        )
        self.store = LocalJobStore(temp_dir=self.temp_dir, ttl_minutes=30)
        self.service = StaticService(
            ReportRetrievalOutcome(
                status=RetrievalOutcomeStatus.USER_INPUT_REQUIRED
            )
        )
        self.app = create_app()
        self.app.dependency_overrides[get_backend_settings] = lambda: self.settings
        self.app.dependency_overrides[get_result_store] = lambda: self.store
        self.app.dependency_overrides[get_report_retrieval_service] = (
            lambda: self.service
        )
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        self.client.close()
        self.store.cleanup_all()
        self.directory.cleanup()

    def _retrieve(self):
        return self.client.post(
            "/api/v1/retrieve",
            files={"slip": ("private-patient-name.png", _png_bytes(), "image/png")},
        )

    def _set_completed_outcome(self) -> None:
        pdf = self.temp_dir / "engine-random-pdf.pdf"
        png = self.temp_dir / "engine-random-image.png"
        bundle = self.temp_dir / "engine-random-bundle.zip"
        pdf.write_bytes(b"%PDF-1.7\nreport")
        png.write_bytes(b"\x89PNG\r\n\x1a\nreport")
        bundle.write_bytes(b"PK\x03\x04bundle")
        self.service.outcome = ReportRetrievalOutcome(
            status=RetrievalOutcomeStatus.COMPLETED,
            reports=[
                RetrievedReport(
                    path=pdf,
                    display_name="PATIENT-9988 private PDF",
                    content_type="application/pdf",
                    size_bytes=pdf.stat().st_size,
                ),
                RetrievedReport(
                    path=png,
                    display_name="PATIENT-9988 private image",
                    content_type="image/png",
                    size_bytes=png.stat().st_size,
                ),
            ],
            bundle=RetrievedReport(
                path=bundle,
                display_name="PATIENT-9988 bundle",
                content_type="application/zip",
                size_bytes=bundle.stat().st_size,
            ),
        )

    def test_synchronous_retrieval_returns_result_and_removes_upload(self) -> None:
        response = self._retrieve()

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "user_input_required")
        self.assertTrue(payload["result_id"])
        self.assertNotIn("private-patient-name", str(payload))
        self.assertEqual(self.service.calls, 1)
        self.assertFalse(any(self.temp_dir.glob("upload-*")))

        fetched = self.client.get(f"/api/v1/results/{payload['result_id']}")
        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(fetched.json(), payload)

    def test_multiple_reports_and_pdf_image_zip_downloads_are_safe(self) -> None:
        self._set_completed_outcome()
        response = self._retrieve()
        payload = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(len(payload["reports"]), 2)
        self.assertEqual(
            [item["display_name"] for item in payload["reports"]],
            ["Report 1", "Report 2"],
        )
        self.assertEqual(payload["bundle"]["content_type"], "application/zip")
        self.assertNotIn("PATIENT-9988", str(payload))
        self.assertNotIn(str(self.temp_dir), str(payload))

        expected = {
            "application/pdf": b"%PDF",
            "image/png": b"\x89PNG",
            "application/zip": b"PK\x03\x04",
        }
        files = [*payload["reports"], payload["bundle"]]
        for item in files:
            with self.subTest(content_type=item["content_type"]):
                download = self.client.get(
                    f"/api/v1/results/{payload['result_id']}/files/{item['file_id']}"
                )
                self.assertEqual(download.status_code, 200)
                self.assertEqual(download.headers["content-type"], item["content_type"])
                self.assertTrue(download.content.startswith(expected[item["content_type"]]))
                self.assertEqual(
                    download.headers["cache-control"], "private, no-store"
                )

    def test_invalid_result_and_path_traversal_return_only_not_found(self) -> None:
        missing = self.client.get("/api/v1/results/not-a-result")
        traversal = self.client.get(
            "/api/v1/results/not-a-result/files/..%2F..%2F.env"
        )

        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.json(), {"detail": "Result not found."})
        self.assertEqual(traversal.status_code, 404)
        self.assertNotIn(".env", traversal.text)

    def test_result_reset_removes_metadata_and_owned_files(self) -> None:
        self._set_completed_outcome()
        payload = self._retrieve().json()

        reset = self.client.delete(f"/api/v1/results/{payload['result_id']}")

        self.assertEqual(reset.status_code, 204)
        self.assertEqual(
            self.client.get(f"/api/v1/results/{payload['result_id']}").status_code,
            404,
        )
        self.assertFalse((self.temp_dir / "engine-random-pdf.pdf").exists())
        self.assertFalse((self.temp_dir / "engine-random-image.png").exists())
        self.assertFalse((self.temp_dir / "engine-random-bundle.zip").exists())

    def test_sensitive_exception_values_are_not_returned_or_logged(self) -> None:
        self.app.dependency_overrides[get_report_retrieval_service] = RaisingService

        with self.assertLogs("backend.routes.synchronous", level="ERROR") as captured:
            response = self._retrieve()

        combined = " ".join(captured.output) + response.text
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["failure_type"], "retrieval_failed")
        self.assertNotIn("PATIENT-9988", combined)
        self.assertNotIn("SECRET-CREDENTIAL", combined)
        self.assertNotIn("/private/report/path", combined)

    def test_background_job_creation_is_disabled_in_synchronous_mode(self) -> None:
        response = self.client.post(
            "/api/v1/jobs",
            files={"slip": ("slip.png", _png_bytes(), "image/png")},
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json(), {"detail": "Background job execution is disabled."}
        )

    def test_retrieve_is_disabled_in_background_mode(self) -> None:
        self.app.dependency_overrides[get_backend_settings] = lambda: replace(
            self.settings, backend_execution_mode="background"
        )

        response = self._retrieve()

        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.service.calls, 0)


class CloudRunEnvironmentTests(unittest.TestCase):
    def test_port_and_execution_mode_are_read_from_environment(self) -> None:
        get_settings.cache_clear()
        try:
            with patch.dict(
                os.environ,
                {"PORT": "8080", "BACKEND_EXECUTION_MODE": "synchronous"},
                clear=True,
            ):
                settings = get_settings()
        finally:
            get_settings.cache_clear()

        self.assertEqual(settings.port, 8080)
        self.assertEqual(settings.backend_execution_mode, "synchronous")

    def test_unhandled_api_errors_are_sanitized(self) -> None:
        app = create_app()

        @app.get("/test-only-failure")
        def fail() -> None:
            raise RuntimeError("PATIENT-9988 SECRET-CREDENTIAL /private/report/path")

        with (
            TestClient(app, raise_server_exceptions=False) as client,
            self.assertLogs("backend.main", level="ERROR") as captured,
        ):
            response = client.get("/test-only-failure")

        combined = response.text + " ".join(captured.output)
        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.json(), {"detail": "The request could not be completed."}
        )
        self.assertNotIn("PATIENT-9988", combined)
        self.assertNotIn("SECRET-CREDENTIAL", combined)
        self.assertNotIn("/private/report/path", combined)


if __name__ == "__main__":
    unittest.main()
