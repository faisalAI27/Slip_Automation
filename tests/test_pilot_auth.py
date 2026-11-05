from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.auth import validate_auth_settings, verify_identity_token
from backend.dependencies import (
    get_backend_settings,
    get_result_store,
    get_job_store,
    get_report_retrieval_service,
)
from backend.jobs import LocalJobStore
from backend.main import create_app
from config.settings import get_settings
from services.models import (
    ReportRetrievalOutcome,
    RetrievalOutcomeStatus,
    RetrievedReport,
)
from tests.test_backend_api import _png_bytes


class PilotAuthTests(TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.settings = replace(
            get_settings(),
            temp_dir=self.root,
            api_auth_mode="firebase",
            firebase_project_id="synthetic-pilot",
            pilot_allowed_uids=("tester-a", "tester-b"),
            backend_execution_mode="synchronous",
        )
        self.store = LocalJobStore(temp_dir=self.root)
        self.service = Mock()
        self.service.retrieve.return_value = ReportRetrievalOutcome(
            status=RetrievalOutcomeStatus.USER_INPUT_REQUIRED
        )
        self.app = create_app()
        self.app.dependency_overrides[get_backend_settings] = lambda: self.settings
        self.app.dependency_overrides[get_result_store] = lambda: self.store
        self.app.dependency_overrides[get_job_store] = lambda: self.store
        self.app.dependency_overrides[get_report_retrieval_service] = (
            lambda: self.service
        )
        self.client = TestClient(self.app)
        self.verifier = patch(
            "backend.auth.verify_identity_token", side_effect=self._verify
        ).start()
        self.addCleanup(patch.stopall)

    def tearDown(self):
        self.client.close()
        self.directory.cleanup()

    @staticmethod
    def _verify(token, project_id):
        if token in {"token-a", "token-b", "outsider"}:
            return {
                "token-a": "tester-a",
                "token-b": "tester-b",
                "outsider": "not-approved",
            }[token]
        raise HTTPException(status_code=401, detail="Sign in again to continue.")

    def test_authentication_rejects_missing_invalid_and_unapproved_tokens_before_retrieval(
        self,
    ):
        for token, code in ((None, 401), ("invalid", 401), ("outsider", 403)):
            response = self.client.post(
                "/api/v1/retrieve",
                headers={} if token is None else {"Authorization": f"Bearer {token}"},
                files={"slip": ("slip.png", _png_bytes(), "image/png")},
            )
            self.assertEqual(response.status_code, code)
        self.service.retrieve.assert_not_called()
        self.assertEqual(list(self.root.iterdir()), [])

    def test_result_is_owned_by_authenticated_tester(self):
        response = self.client.post(
            "/api/v1/retrieve",
            headers={"Authorization": "Bearer token-a"},
            data={"hospital": "northwest"},
            files={"slip": ("slip.png", _png_bytes(), "image/png")},
        )
        self.assertEqual(response.status_code, 200)
        result_id = response.json()["result_id"]
        self.assertEqual(self.store.get(result_id).owner_uid, "tester-a")
        self.assertNotIn("owner_uid", response.text)
        self.assertEqual(
            self.client.get(
                f"/api/v1/results/{result_id}",
                headers={"Authorization": "Bearer token-b"},
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.delete(
                f"/api/v1/results/{result_id}",
                headers={"Authorization": "Bearer token-b"},
            ).status_code,
            404,
        )
        self.assertIsNotNone(self.store.get(result_id))
        self.assertEqual(
            self.client.delete(
                f"/api/v1/results/{result_id}",
                headers={"Authorization": "Bearer token-a"},
            ).status_code,
            204,
        )

    def test_downloads_and_background_status_enforce_ownership(self):
        upload = self.root / "upload.png"
        upload.write_bytes(_png_bytes())
        report = self.root / "report.pdf"
        report.write_bytes(b"%PDF-1.7\nsynthetic")
        self.store.create("job", upload, owner_uid="tester-a")
        self.store.complete(
            "job",
            [
                (
                    "file",
                    RetrievedReport(
                        path=report,
                        display_name="Report",
                        content_type="application/pdf",
                        size_bytes=report.stat().st_size,
                    ),
                )
            ],
            None,
        )
        for route in (
            "/api/v1/results/job/files/file",
            "/api/v1/jobs/job/files/file",
            "/api/v1/jobs/job",
        ):
            self.assertEqual(
                self.client.get(
                    route, headers={"Authorization": "Bearer token-b"}
                ).status_code,
                404,
            )
            self.assertEqual(
                self.client.get(
                    route, headers={"Authorization": "Bearer token-a"}
                ).status_code,
                200,
            )
            self.assertEqual(self.client.get(route).status_code, 401)

    def test_health_is_public_and_api_is_protected(self):
        self.assertEqual(self.client.get("/health").status_code, 200)
        self.assertEqual(self.client.get("/api/v1/results/unknown").status_code, 401)
        self.assertEqual(
            self.client.post(
                "/api/v1/jobs", files={"slip": ("slip.png", _png_bytes(), "image/png")}
            ).status_code,
            401,
        )

    def test_firebase_configuration_fails_closed(self):
        for settings in (
            replace(self.settings, firebase_project_id=""),
            replace(self.settings, pilot_allowed_uids=()),
            replace(self.settings, api_auth_mode="invalid"),
        ):
            with self.assertRaises(RuntimeError):
                validate_auth_settings(settings)

    def test_sdk_verifies_signature_audience_expiry_and_revocation(self):
        # Call the real boundary with only Google's SDK call replaced.
        patch.stopall()
        with (
            patch("backend.auth._firebase_app", return_value=Mock()) as app,
            patch(
                "firebase_admin.auth.verify_id_token", return_value={"uid": "tester-a"}
            ) as verify,
        ):
            self.assertEqual(
                verify_identity_token("synthetic-token", "synthetic-pilot"), "tester-a"
            )
            app.assert_called_once_with("synthetic-pilot")
            self.assertTrue(verify.call_args.kwargs["check_revoked"])
