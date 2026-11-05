from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from unittest import TestCase

from scripts.firebase_mobile_config import build_defines

ROOT = Path(__file__).resolve().parents[1]


class PilotDeploymentTests(TestCase):
    def test_android_config_generator_uses_matching_package_and_https(self):
        config = {
            "project_info": {"project_id": "synthetic-pilot", "project_number": "123"},
            "client": [
                {
                    "client_info": {
                        "android_client_info": {
                            "package_name": "com.slipautomation.reportapp"
                        },
                        "mobilesdk_app_id": "1:123:android:test",
                    },
                    "api_key": [{"current_key": "synthetic-public-app-key"}],
                }
            ],
        }
        defines = build_defines(config, "https://api.example.test/")
        self.assertEqual(defines["API_AUTH_MODE"], "firebase")
        self.assertEqual(defines["API_EXECUTION_MODE"], "synchronous")
        self.assertEqual(defines["FIREBASE_PROJECT_ID"], "synthetic-pilot")
        for url in (
            "http://api.example.test",
            "https://user:secret@api.example.test",
            "https://api.example.test/?token=secret",
        ):
            with self.assertRaises(ValueError):
                build_defines(config, url)
        config["client"][0]["client_info"]["android_client_info"]["package_name"] = (
            "unrelated.app"
        )
        with self.assertRaises(ValueError):
            build_defines(config, "https://api.example.test")

    def test_public_deploy_guard_rejects_missing_auth_or_placeholder_testers(self):
        with TemporaryDirectory() as folder:
            env = Path(folder) / "env.yaml"
            for value in (
                'API_AUTH_MODE: "none"\n',
                'API_AUTH_MODE: "firebase"\nFIREBASE_PROJECT_ID: "synthetic-pilot"\nPILOT_ALLOWED_UIDS: "REPLACE_WITH_TESTER_UID"\n',
            ):
                env.write_text(value)
                result = subprocess.run(
                    [
                        "bash",
                        str(ROOT / "scripts/deploy_cloud_run_pilot.sh"),
                        "synthetic-pilot",
                        "asia-south1",
                        "synthetic-image",
                        str(env),
                    ],
                    capture_output=True,
                    text=True,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("gcloud", result.stderr)
