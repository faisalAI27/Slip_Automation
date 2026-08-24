import unittest

from config.settings import _as_url_overrides


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


if __name__ == "__main__":
    unittest.main()
