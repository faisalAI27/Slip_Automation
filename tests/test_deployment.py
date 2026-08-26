import json
import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from backend.jobs import LocalJobRunner, LocalJobStore
from backend.main import (
    create_app,
    shutdown_backend_resources,
    validate_production_settings,
)
from browser_agent.session import BrowserSession, BrowserSessionConfig
from config.settings import PROJECT_ROOT, get_settings
from services.models import RetrievedReport


class ProductionConfigurationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.secure = replace(
            get_settings(),
            app_env="production",
            debug_mode=False,
            document_ai_provider="gemini",
            gemini_api_key="test-only-value",
            browser_headless=True,
            allow_insecure_report_portals=False,
            backend_max_concurrent_jobs=1,
            job_ttl_minutes=30,
        )

    def test_secure_production_settings_are_accepted(self) -> None:
        validate_production_settings(self.secure)

    def test_production_rejects_debug_or_unsafe_browser_settings(self) -> None:
        invalid_settings = (
            replace(self.secure, debug_mode=True),
            replace(self.secure, browser_headless=False),
            replace(self.secure, allow_insecure_report_portals=True),
            replace(self.secure, gemini_api_key=None),
        )

        for settings in invalid_settings:
            with self.subTest(settings=settings), self.assertRaises(RuntimeError):
                validate_production_settings(settings)

    def test_docker_image_is_pinned_non_root_and_has_no_secret_value(self) -> None:
        dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")
        requirements = (PROJECT_ROOT / "requirements-backend.txt").read_text(
            encoding="utf-8"
        )

        self.assertIn("playwright/python:v1.62.0-noble@sha256:", dockerfile)
        self.assertIn("playwright==1.62.0", requirements)
        self.assertIn("USER pwuser", dockerfile)
        self.assertIn("--workers 1", dockerfile)
        self.assertNotIn("GEMINI_API_KEY", dockerfile)
        self.assertNotIn("--no-sandbox", dockerfile)
        self.assertNotIn("alpine", dockerfile.casefold())

    def test_docker_context_excludes_environment_files(self) -> None:
        ignored = (PROJECT_ROOT / ".dockerignore").read_text(encoding="utf-8")

        self.assertIn(".env\n", ignored)
        self.assertIn(".env.*", ignored)
        self.assertIn("!.env.example", ignored)

    def test_playwright_seccomp_profile_enables_user_namespace_sandbox(self) -> None:
        profile = json.loads(
            (PROJECT_ROOT / "seccomp_profile.json").read_text(encoding="utf-8")
        )
        sandbox_rules = [
            rule
            for rule in profile["syscalls"]
            if {"clone", "setns", "unshare"}.issubset(rule.get("names", []))
            and rule.get("action") == "SCMP_ACT_ALLOW"
        ]
        e2e_script = (PROJECT_ROOT / "scripts" / "container_e2e.sh").read_text(
            encoding="utf-8"
        )

        self.assertTrue(sandbox_rules)
        self.assertIn('--security-opt "seccomp=$SECCOMP_PROFILE"', e2e_script)


class BackendLifecycleTests(unittest.TestCase):
    def test_startup_health_and_graceful_shutdown_hooks_run(self) -> None:
        app = create_app()
        with (
            patch("backend.main.initialize_backend") as initialize,
            patch("backend.main.shutdown_cached_backend_resources") as shutdown,
            TestClient(app) as client,
        ):
            response = client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})
        initialize.assert_called_once()
        shutdown.assert_called_once_with()
        self.assertFalse(app.state.accepting_jobs)

    def test_shutdown_waits_for_runner_before_cleaning_store(self) -> None:
        calls: list[object] = []
        runner = MagicMock()
        store = MagicMock()
        runner.shutdown.side_effect = lambda *, wait: calls.append(("runner", wait))
        store.cleanup_all.side_effect = lambda: calls.append("store")

        shutdown_backend_resources(runner, store)

        self.assertEqual(calls, [("runner", True), "store"])

    def test_shutdown_cleans_store_even_when_runner_shutdown_fails(self) -> None:
        runner = MagicMock()
        store = MagicMock()
        runner.shutdown.side_effect = RuntimeError("executor failure")

        with self.assertRaises(RuntimeError):
            shutdown_backend_resources(runner, store)

        store.cleanup_all.assert_called_once_with()

    def test_local_runner_drains_active_and_cancels_queued_jobs(self) -> None:
        runner = LocalJobRunner(max_concurrent_jobs=1)
        started = Event()
        release = Event()
        first = runner.submit("active", lambda: (started.set(), release.wait(2)))
        self.assertTrue(started.wait(1))
        queued = runner.submit("queued", lambda: None)
        shutdown = Thread(target=runner.shutdown, kwargs={"wait": True})

        shutdown.start()
        for _ in range(100):
            if queued.cancelled():
                break
            release.wait(0.01)
        release.set()
        shutdown.join(2)

        self.assertFalse(shutdown.is_alive())
        self.assertTrue(first.done())
        self.assertTrue(queued.cancelled())


class RuntimeCleanupTests(unittest.TestCase):
    def test_cleanup_all_removes_jobs_uploads_and_reports(self) -> None:
        with TemporaryDirectory() as directory:
            temp_dir = Path(directory)
            upload = temp_dir / "upload.png"
            report = temp_dir / "report.pdf"
            upload.write_bytes(b"upload")
            report.write_bytes(b"%PDF-1.7\nreport")
            store = LocalJobStore(temp_dir=temp_dir)
            store.create("job", upload)
            stored = store.complete(
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

            self.assertTrue(stored)
            self.assertEqual(store.cleanup_all(), 1)
            self.assertIsNone(store.get("job"))
            self.assertFalse(upload.exists())
            self.assertFalse(report.exists())

    def test_browser_launch_is_headless_with_chromium_sandbox(self) -> None:
        manager = MagicMock()
        playwright = manager.start.return_value
        browser = playwright.chromium.launch.return_value
        context = browser.new_context.return_value

        with patch("browser_agent.session.sync_playwright", return_value=manager):
            session = BrowserSession(BrowserSessionConfig(headless=True))
            session.start()
            session.close()

        playwright.chromium.launch.assert_called_once_with(
            headless=True,
            chromium_sandbox=True,
            args=["--disable-dev-shm-usage"],
        )
        context.close.assert_called_once_with()
        browser.close.assert_called_once_with()
        playwright.stop.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
