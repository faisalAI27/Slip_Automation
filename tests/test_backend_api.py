from concurrent.futures import Future
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Lock
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

from backend.dependencies import (
    get_backend_settings,
    get_job_runner,
    get_job_store,
    get_report_retrieval_service,
)
from backend.jobs import LocalJobRunner, LocalJobStore
from backend.main import create_app
from config.settings import get_settings
from services.models import (
    ProgressEvent,
    ProgressStage,
    ReportRetrievalOutcome,
    RetrievalOutcomeStatus,
    RetrievedReport,
)


def _png_bytes() -> bytes:
    output = BytesIO()
    Image.new("RGB", (10, 8), color="white").save(output, format="PNG")
    return output.getvalue()


class ImmediateRunner:
    def submit(self, job_id, task):
        del job_id
        future = Future()
        try:
            task()
            future.set_result(None)
        except Exception as exc:
            future.set_exception(exc)
        return future

    def shutdown(self, *, wait=True):
        del wait


class HeldRunner:
    def __init__(self):
        self.tasks = []

    def submit(self, job_id, task):
        del job_id
        self.tasks.append(task)
        return Future()

    def run_all(self):
        for task in self.tasks:
            task()

    def shutdown(self, *, wait=True):
        del wait


class StaticService:
    def __init__(self, outcome):
        self.outcome = outcome
        self.calls = 0

    def retrieve(self, image_path, progress_callback=None):
        self.calls += 1
        if progress_callback:
            progress_callback(
                ProgressEvent(
                    stage=ProgressStage.RETRIEVING_REPORTS,
                    message="Retrieving your report",
                )
            )
        return self.outcome


class RaisingService:
    def retrieve(self, image_path, progress_callback=None):
        del image_path, progress_callback
        raise RuntimeError("PATIENT-123 ACCESS-CODE-SECRET")


class BackendApiTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.temp_dir = Path(self.directory.name)
        self.settings = replace(
            get_settings(),
            temp_dir=self.temp_dir,
            max_upload_mb=1,
            max_report_download_mb=1,
            job_ttl_minutes=30,
        )
        self.store = LocalJobStore(temp_dir=self.temp_dir, ttl_minutes=30)
        self.runner = ImmediateRunner()
        self.service = StaticService(
            ReportRetrievalOutcome(status=RetrievalOutcomeStatus.USER_INPUT_REQUIRED)
        )
        self.app = create_app()
        self.app.dependency_overrides[get_backend_settings] = lambda: self.settings
        self.app.dependency_overrides[get_job_store] = lambda: self.store
        self.app.dependency_overrides[get_job_runner] = lambda: self.runner
        self.app.dependency_overrides[get_report_retrieval_service] = (
            lambda: self.service
        )
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        self.directory.cleanup()

    def _post_image(self, filename="slip.png", data=None):
        return self.client.post(
            "/api/v1/jobs",
            files={"slip": (filename, data or _png_bytes(), "image/png")},
        )

    def _set_completed_outcome(self, report_count=1, bundle=False):
        reports = []
        for index in range(report_count):
            path = self.temp_dir / f"synthetic-{index}.pdf"
            path.write_bytes(b"%PDF-1.7\nsynthetic")
            reports.append(
                RetrievedReport(
                    path=path,
                    display_name=f"PATIENT-123 private label {index + 1}",
                    content_type="application/pdf",
                    size_bytes=path.stat().st_size,
                )
            )
        bundle_file = None
        if bundle:
            path = self.temp_dir / "synthetic-bundle.zip"
            path.write_bytes(b"PK\x03\x04synthetic")
            bundle_file = RetrievedReport(
                path=path,
                display_name="All reports",
                content_type="application/zip",
                size_bytes=path.stat().st_size,
            )
        self.service.outcome = ReportRetrievalOutcome(
            status=RetrievalOutcomeStatus.COMPLETED,
            reports=reports,
            bundle=bundle_file,
        )

    def test_health_endpoint_does_not_start_retrieval(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})
        self.assertEqual(self.service.calls, 0)

    def test_cors_allows_only_a_configured_origin(self):
        configured = replace(
            self.settings,
            api_allowed_origins=("https://mobile-web.example",),
        )
        with patch("backend.main.get_settings", return_value=configured):
            cors_app = create_app()
        with TestClient(cors_app) as client:
            allowed = client.options(
                "/health",
                headers={
                    "Origin": "https://mobile-web.example",
                    "Access-Control-Request-Method": "GET",
                },
            )
            rejected = client.options(
                "/health",
                headers={
                    "Origin": "https://untrusted.example",
                    "Access-Control-Request-Method": "GET",
                },
            )
        self.assertEqual(
            allowed.headers.get("access-control-allow-origin"),
            "https://mobile-web.example",
        )
        self.assertNotIn("access-control-allow-origin", rejected.headers)

    def test_valid_upload_creates_job_with_generated_id(self):
        response = self._post_image(filename="private-patient-name.png")
        self.assertEqual(response.status_code, 202)
        payload = response.json()
        self.assertEqual(payload["status"], "queued")
        self.assertNotIn("private-patient-name", payload["job_id"])
        self.assertEqual(self.service.calls, 1)

    def test_invalid_image_is_rejected(self):
        response = self._post_image(data=b"not an image")
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("not an image", response.text)

    def test_unsupported_upload_is_rejected(self):
        response = self._post_image(filename="slip.gif")
        self.assertEqual(response.status_code, 415)

    def test_oversized_image_is_rejected_before_decoding(self):
        response = self._post_image(data=b"x" * (1024 * 1024 + 1))
        self.assertEqual(response.status_code, 413)

    def test_status_polling_reports_queued_then_completed(self):
        held = HeldRunner()
        self.app.dependency_overrides[get_job_runner] = lambda: held
        self._set_completed_outcome()
        created = self._post_image().json()

        queued = self.client.get(f"/api/v1/jobs/{created['job_id']}").json()
        self.assertEqual(queued["status"], "queued")
        self.assertEqual(queued["stage"], "uploaded")

        held.run_all()
        completed = self.client.get(f"/api/v1/jobs/{created['job_id']}").json()
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(len(completed["reports"]), 1)

    def test_successful_mocked_retrieval_and_safe_download(self):
        self._set_completed_outcome()
        job_id = self._post_image().json()["job_id"]
        status_payload = self.client.get(f"/api/v1/jobs/{job_id}").json()
        report = status_payload["reports"][0]

        response = self.client.get(f"/api/v1/jobs/{job_id}/files/{report['file_id']}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))
        self.assertEqual(response.headers["cache-control"], "private, no-store")

    def test_retrieval_failure_is_safe(self):
        self.service.outcome = ReportRetrievalOutcome(
            status=RetrievalOutcomeStatus.FAILED,
            safe_failure_type="retrieval_failed",
        )
        job_id = self._post_image().json()["job_id"]
        payload = self.client.get(f"/api/v1/jobs/{job_id}").json()
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["failure_type"], "retrieval_failed")

    def test_user_input_required_outcome(self):
        job_id = self._post_image().json()["job_id"]
        payload = self.client.get(f"/api/v1/jobs/{job_id}").json()
        self.assertEqual(payload["status"], "user_input_required")
        self.assertEqual(payload["stage"], "user_input_required")

    def test_verification_required_outcome(self):
        self.service.outcome = ReportRetrievalOutcome(
            status=RetrievalOutcomeStatus.VERIFICATION_REQUIRED
        )
        job_id = self._post_image().json()["job_id"]
        payload = self.client.get(f"/api/v1/jobs/{job_id}").json()
        self.assertEqual(payload["status"], "verification_required")

    def test_multiple_reports_and_zip_bundle_metadata(self):
        self._set_completed_outcome(report_count=2, bundle=True)
        job_id = self._post_image().json()["job_id"]
        payload = self.client.get(f"/api/v1/jobs/{job_id}").json()
        self.assertEqual(len(payload["reports"]), 2)
        self.assertEqual(
            [item["display_name"] for item in payload["reports"]],
            ["Report 1", "Report 2"],
        )
        self.assertTrue(payload["bundle_available"])
        self.assertEqual(payload["bundle"]["content_type"], "application/zip")
        self.assertNotIn(str(self.temp_dir), str(payload))
        self.assertNotIn("PATIENT-123", str(payload))

    def test_invalid_file_id_and_path_traversal_are_rejected(self):
        self._set_completed_outcome()
        job_id = self._post_image().json()["job_id"]
        invalid = self.client.get(f"/api/v1/jobs/{job_id}/files/not-a-file")
        traversal = self.client.get(f"/api/v1/jobs/{job_id}/files/..%2F..%2F.env")
        self.assertEqual(invalid.status_code, 404)
        self.assertEqual(traversal.status_code, 404)

    def test_missing_job_is_not_exposed(self):
        response = self.client.get("/api/v1/jobs/unknown-job")
        self.assertEqual(response.status_code, 404)

    def test_sensitive_exception_values_never_appear_in_response_or_logs(self):
        self.app.dependency_overrides[get_report_retrieval_service] = RaisingService
        with self.assertLogs("backend.routes.reports", level="ERROR") as captured:
            job_id = self._post_image().json()["job_id"]
        payload = self.client.get(f"/api/v1/jobs/{job_id}").json()
        combined = " ".join(captured.output) + str(payload)
        self.assertNotIn("PATIENT-123", combined)
        self.assertNotIn("ACCESS-CODE-SECRET", combined)
        self.assertNotIn("RuntimeError(", combined)


class LocalJobInfrastructureTests(unittest.TestCase):
    def test_expired_job_is_removed_and_all_files_are_cleaned(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            current = [datetime(2026, 1, 1, tzinfo=timezone.utc)]
            store = LocalJobStore(
                temp_dir=root,
                ttl_minutes=1,
                clock=lambda: current[0],
            )
            upload = root / "upload-test.png"
            report = root / "report-test.pdf"
            upload.write_bytes(_png_bytes())
            report.write_bytes(b"%PDF-1.7\ntest")
            store.create("job", upload)
            store.complete(
                "job",
                [
                    (
                        "file",
                        RetrievedReport(
                            path=report,
                            display_name="Report 1",
                            content_type="application/pdf",
                            size_bytes=report.stat().st_size,
                        ),
                    )
                ],
                None,
            )

            current[0] += timedelta(minutes=2)
            self.assertEqual(store.cleanup_expired(), 1)
            self.assertIsNone(store.get("job"))
            self.assertFalse(upload.exists())
            self.assertFalse(report.exists())

    def test_runner_enforces_single_job_concurrency(self):
        runner = LocalJobRunner(max_concurrent_jobs=1)
        first_started = Event()
        second_started = Event()
        release = Event()
        active = 0
        maximum_active = 0
        lock = Lock()

        def task(started):
            nonlocal active, maximum_active
            with lock:
                active += 1
                maximum_active = max(maximum_active, active)
            started.set()
            release.wait(2)
            with lock:
                active -= 1

        first = runner.submit("one", lambda: task(first_started))
        second = runner.submit("two", lambda: task(second_started))
        try:
            self.assertTrue(first_started.wait(1))
            self.assertFalse(second_started.wait(0.1))
            self.assertEqual(maximum_active, 1)
        finally:
            release.set()
            first.result(timeout=2)
            second.result(timeout=2)
            runner.shutdown()


if __name__ == "__main__":
    unittest.main()
