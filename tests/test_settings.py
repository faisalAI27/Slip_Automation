import os
import unittest
from unittest.mock import patch

from config.settings import _as_hosts, _as_url_overrides, get_settings


class SettingsTests(unittest.TestCase):
    def test_portal_url_overrides_are_normalized(self) -> None:
        overrides = _as_url_overrides(
            '{" Reports.Example.Test ": " https://secure.example.test/login "}'
        )

        self.assertEqual(
            overrides,
            {"reports.example.test": "https://secure.example.test/login"},
        )

    def test_invalid_portal_url_overrides_are_ignored(self) -> None:
        self.assertEqual(_as_url_overrides("not-json"), {})
        self.assertEqual(_as_url_overrides('["not", "an", "object"]'), {})

    def test_insecure_portal_hosts_are_exact_and_normalized(self) -> None:
        self.assertEqual(
            _as_hosts(" RMI.OliveCliq.org., reports.example.test, rmi.olivecliq.org "),
            ("rmi.olivecliq.org", "reports.example.test"),
        )

    def test_gemini_compatibility_defaults_are_centralized(self) -> None:
        get_settings.cache_clear()
        try:
            with patch.dict(os.environ, {}, clear=True):
                settings = get_settings()
        finally:
            get_settings.cache_clear()

        self.assertEqual(
            settings.gemini_base_url,
            "https://generativelanguage.googleapis.com/v1beta/openai/",
        )
        self.assertEqual(settings.gemini_timeout_seconds, 60)
        self.assertEqual(settings.gemini_credential_focus_timeout_seconds, 12)
        self.assertEqual(settings.gemini_reasoning_effort, "low")
        self.assertFalse(settings.allow_insecure_report_portals)
        self.assertEqual(settings.insecure_report_portal_hosts, ())


if __name__ == "__main__":
    unittest.main()
