import unittest

from browser_agent.errors import UnsafeNavigationError
from browser_agent.safety import redact_url_for_display, validate_public_url, registrable_domain


def _public_resolver(_hostname: str, _port: int) -> list[str]:
    return ["93.184.216.34"]


class BrowserSafetyTests(unittest.TestCase):
    def test_private_hosting_tenants_are_distinct(self) -> None:
        for suffix in ("github.io", "appspot.com", "blogspot.com", "co.jp"):
            with self.subTest(suffix=suffix):
                self.assertNotEqual(
                    registrable_domain(f"hospital.{suffix}"),
                    registrable_domain(f"unrelated.{suffix}"),
                )

    def test_known_subdomains_share_tenant_but_unknown_suffixes_do_not(self) -> None:
        self.assertEqual(registrable_domain("reports.hospital.com.pk"), "hospital.com.pk")
        self.assertEqual(registrable_domain("reports.hospital.github.io"), "hospital.github.io")
        self.assertEqual(registrable_domain("one.hospital.unknown-suffix"), "one.hospital.unknown-suffix")
        self.assertEqual(registrable_domain("93.184.216.34"), "93.184.216.34")

    def test_safe_public_https_url_is_allowed(self) -> None:
        result = validate_public_url(
            "https://example.test/reports", resolver=_public_resolver
        )

        self.assertEqual(result.scheme, "https")
        self.assertEqual(result.hostname, "example.test")

    def test_unsafe_schemes_are_blocked(self) -> None:
        for value in (
            "javascript:alert(1)",
            "file:///etc/passwd",
            "data:text/plain,test",
            "ftp://example.test/file",
            "chrome://settings",
            "about:blank",
        ):
            with self.subTest(value=value), self.assertRaises(UnsafeNavigationError):
                validate_public_url(value, resolver=_public_resolver)

    def test_localhost_and_private_addresses_are_blocked(self) -> None:
        values = (
            "http://localhost/report",
            "http://127.0.0.1/report",
            "http://0.0.0.0/report",
            "http://[::1]/report",
            "http://192.168.1.20/report",
            "http://169.254.1.1/report",
        )
        for value in values:
            with self.subTest(value=value), self.assertRaises(UnsafeNavigationError):
                validate_public_url(value, resolver=_public_resolver)

    def test_public_hostname_resolving_private_is_blocked(self) -> None:
        with self.assertRaises(UnsafeNavigationError):
            validate_public_url(
                "https://public-looking.test/report",
                resolver=lambda _host, _port: ["10.0.0.8"],
            )

    def test_display_url_removes_query_values_and_fragment(self) -> None:
        display = redact_url_for_display(
            "https://example.test/report?token=secret#patient"
        )

        self.assertEqual(display, "https://example.test/report?[redacted]")
        self.assertNotIn("secret", display)
        self.assertNotIn("patient", display)


if __name__ == "__main__":
    unittest.main()
