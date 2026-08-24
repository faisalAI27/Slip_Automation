import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from browser_agent.session import BrowserSession, BrowserSessionConfig


class _Download:
    def __init__(self, body: bytes = b"%PDF-1.7\nreport") -> None:
        self.cancelled = False
        self.suggested_filename = "report.pdf"
        self.body = body

    def cancel(self) -> None:
        self.cancelled = True

    def save_as(self, path: str) -> None:
        Path(path).write_bytes(self.body)


class _Page:
    def __init__(self, url: str = "https://example.test/") -> None:
        self.url = url
        self.closed = False
        self.handlers: list[str] = []
        self.locator_value: _Locator | None = None
        self.wait_callback = None
        self.pdf_body = b"%PDF-1.7\nprinted report"

    def on(self, event: str, _handler: object) -> None:
        self.handlers.append(event)

    def close(self) -> None:
        self.closed = True

    def locator(self, _selector: str):
        return self.locator_value

    def wait_for_timeout(self, _milliseconds: float) -> None:
        if self.wait_callback:
            self.wait_callback()

    def wait_for_load_state(self, _state: str, *, timeout: float) -> None:
        return None

    def emulate_media(self, *, media: str) -> None:
        return None

    def pdf(self, *, path: str, **_kwargs: object) -> None:
        Path(path).write_bytes(self.pdf_body)


class _Locator:
    def __init__(self, on_click=None, resource=None) -> None:
        self.on_click = on_click
        self.resource = resource

    def count(self) -> int:
        return 1

    def is_visible(self) -> bool:
        return True

    def is_enabled(self) -> bool:
        return True

    def click(self) -> None:
        if self.on_click:
            self.on_click()

    def evaluate(self, _script: str):
        return self.resource


class _Response:
    def __init__(
        self,
        body: bytes,
        content_type: str = "application/pdf",
        *,
        url: str = "https://reports.example.test/report.pdf",
        status: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.url = url
        self.status = status
        self.ok = 200 <= status < 300
        self.headers = headers or {
            "content-length": str(len(body)),
            "content-type": content_type,
        }
        self._body = body

    def body(self) -> bytes:
        return self._body


class _RequestContext:
    def __init__(
        self,
        body: bytes | None = None,
        *,
        responses: list[_Response] | None = None,
    ) -> None:
        self.responses = responses or [_Response(body or b"")]
        self.requests: list[tuple[str, float, int | None]] = []

    def get(self, url: str, *, timeout: float, max_redirects: int | None = None):
        self.requests.append((url, timeout, max_redirects))
        return self.responses.pop(0)


class _Context:
    def __init__(self, body: bytes) -> None:
        self.request = _RequestContext(body)


class _RouteRequest:
    def __init__(self, url: str, page: _Page, method: str = "GET") -> None:
        self.url = url
        self.method = method
        self.frame = type("Frame", (), {"page": page})()

    def is_navigation_request(self) -> bool:
        return True


class _Route:
    def __init__(self, request: _RouteRequest) -> None:
        self.request = request
        self.aborted = False
        self.continued = False
        self.fulfilled: dict[str, object] | None = None

    def abort(self, _reason: str) -> None:
        self.aborted = True

    def continue_(self) -> None:
        self.continued = True

    def fulfill(self, **kwargs: object) -> None:
        self.fulfilled = kwargs


class BrowserSessionControlTests(unittest.TestCase):
    def test_configured_http_navigation_is_blocked_and_rewritten_to_https(self) -> None:
        page = _Page("https://secure.example.test/login")
        session = BrowserSession(
            BrowserSessionConfig(
                navigation_url_rewrites={
                    "legacy.example.test": "https://secure.example.test"
                }
            ),
            resolver=lambda _host, _port: ["93.184.216.34"],
        )
        route = _Route(
            _RouteRequest(
                "http://legacy.example.test/reports/latest?source=portal",
                page,
            )
        )

        session._route_request(route)  # type: ignore[arg-type,attr-defined]

        self.assertFalse(route.aborted)
        self.assertFalse(route.continued)
        self.assertIsNotNone(route.fulfilled)
        self.assertEqual(
            route.fulfilled["headers"]["location"],  # type: ignore[index]
            "https://secure.example.test/reports/latest?source=portal",
        )

    def test_configured_http_post_is_blocked_without_replay(self) -> None:
        page = _Page("https://secure.example.test/login")
        session = BrowserSession(
            BrowserSessionConfig(
                navigation_url_rewrites={
                    "legacy.example.test": "https://secure.example.test"
                }
            ),
            resolver=lambda _host, _port: ["93.184.216.34"],
        )
        route = _Route(
            _RouteRequest(
                "http://legacy.example.test/session",
                page,
                method="POST",
            )
        )

        session._route_request(route)  # type: ignore[arg-type,attr-defined]

        self.assertTrue(route.aborted)
        self.assertIsNone(route.fulfilled)

    def test_unsolicited_download_is_cancelled(self) -> None:
        session = BrowserSession(BrowserSessionConfig())
        download = _Download()

        session._handle_download(download)  # type: ignore[attr-defined]

        self.assertTrue(download.cancelled)
        self.assertIn("unsolicited", " ".join(session.warnings).casefold())

    def test_expected_download_is_not_cancelled(self) -> None:
        session = BrowserSession(BrowserSessionConfig())
        session._expected_download = True  # type: ignore[attr-defined]
        download = _Download()

        session._handle_download(download)  # type: ignore[attr-defined]

        self.assertFalse(download.cancelled)

    def test_unsolicited_popup_is_closed(self) -> None:
        session = BrowserSession(BrowserSessionConfig())
        session._page = _Page()  # type: ignore[attr-defined]
        popup = _Page()

        session._handle_new_page(popup)  # type: ignore[attr-defined]

        self.assertTrue(popup.closed)

    def test_expected_popup_is_captured_and_prepared(self) -> None:
        session = BrowserSession(BrowserSessionConfig())
        session._page = _Page()  # type: ignore[attr-defined]
        session._expected_popup = True  # type: ignore[attr-defined]
        popup = _Page()

        session._handle_new_page(popup)  # type: ignore[attr-defined]

        self.assertFalse(popup.closed)
        self.assertIs(session._pending_popup, popup)  # type: ignore[attr-defined]
        self.assertEqual(set(popup.handlers), {"dialog", "download", "response"})

    def test_controlled_click_adopts_valid_expected_popup(self) -> None:
        session = BrowserSession(
            BrowserSessionConfig(),
            resolver=lambda _host, _port: ["93.184.216.34"],
        )
        current = _Page()
        popup = _Page("https://reports.example.test/report")
        current.locator_value = _Locator(
            on_click=lambda: session._handle_new_page(popup)  # type: ignore[attr-defined]
        )
        session._page = current  # type: ignore[attr-defined]

        session.click("button_1")

        self.assertIs(session.page, popup)
        self.assertFalse(popup.closed)

    def test_embedded_https_report_is_fetched_with_browser_cookies(self) -> None:
        session = BrowserSession(
            BrowserSessionConfig(),
            resolver=lambda _host, _port: ["93.184.216.34"],
        )
        page = _Page("https://reports.example.test/viewer")
        page.locator_value = _Locator(
            resource={
                "tag": "iframe",
                "url": "https://reports.example.test/report.pdf",
                "download": False,
            }
        )
        session._page = page  # type: ignore[attr-defined]
        session._context = _Context(b"%PDF-1.7\nreport")  # type: ignore[attr-defined]

        with TemporaryDirectory() as directory:
            destination = Path(directory) / "report.part"
            session.capture_report(
                "resource_1",
                destination,
                allowed_domains={"example.test"},
                max_bytes=1024,
            )

            self.assertEqual(destination.read_bytes(), b"%PDF-1.7\nreport")

    def test_configured_http_report_resource_is_upgraded_before_fetch(self) -> None:
        session = BrowserSession(
            BrowserSessionConfig(
                navigation_url_rewrites={
                    "legacy.example.test": "https://secure.example.test"
                }
            ),
            resolver=lambda _host, _port: ["93.184.216.34"],
        )
        page = _Page("https://secure.example.test/reports")
        page.locator_value = _Locator(
            resource={
                "tag": "a",
                "url": "http://legacy.example.test/report/download/123",
                "download": True,
            }
        )
        request = _RequestContext(
            responses=[
                _Response(
                    b"%PDF-1.7\nreport",
                    url="https://secure.example.test/report/download/123",
                )
            ]
        )
        session._page = page  # type: ignore[attr-defined]
        session._context = type("Context", (), {"request": request})()  # type: ignore[attr-defined]

        with TemporaryDirectory() as directory:
            destination = Path(directory) / "report.part"
            session.capture_report(
                "resource_1",
                destination,
                allowed_domains={"example.test"},
                max_bytes=1024,
            )

            self.assertTrue(destination.read_bytes().startswith(b"%PDF"))
        self.assertEqual(
            request.requests[0][0],
            "https://secure.example.test/report/download/123",
        )
        self.assertEqual(request.requests[0][2], 0)

    def test_configured_http_report_redirect_is_upgraded_before_following(self) -> None:
        session = BrowserSession(
            BrowserSessionConfig(
                navigation_url_rewrites={
                    "legacy.example.test": "https://secure.example.test"
                }
            ),
            resolver=lambda _host, _port: ["93.184.216.34"],
        )
        page = _Page("https://secure.example.test/reports")
        page.locator_value = _Locator(
            resource={
                "tag": "iframe",
                "url": "https://secure.example.test/report/latest",
                "download": False,
            }
        )
        request = _RequestContext(
            responses=[
                _Response(
                    b"",
                    url="https://secure.example.test/report/latest",
                    status=302,
                    headers={"location": "http://legacy.example.test/report/123.pdf"},
                ),
                _Response(
                    b"%PDF-1.7\nreport",
                    url="https://secure.example.test/report/123.pdf",
                ),
            ]
        )
        session._page = page  # type: ignore[attr-defined]
        session._context = type("Context", (), {"request": request})()  # type: ignore[attr-defined]

        with TemporaryDirectory() as directory:
            session.capture_report(
                "resource_1",
                Path(directory) / "report.part",
                allowed_domains={"example.test"},
                max_bytes=1024,
            )

        self.assertEqual(
            [item[0] for item in request.requests],
            [
                "https://secure.example.test/report/latest",
                "https://secure.example.test/report/123.pdf",
            ],
        )

    def test_validated_click_download_is_retained_for_agent_capture(self) -> None:
        session = BrowserSession(
            BrowserSessionConfig(),
            resolver=lambda _host, _port: ["93.184.216.34"],
        )
        download = _Download()
        session._expected_download = True  # type: ignore[attr-defined]

        session._handle_download(download)  # type: ignore[attr-defined]

        self.assertTrue(session.has_pending_report_download)
        self.assertEqual(session.pending_report_file_type, "pdf")
        with TemporaryDirectory() as directory:
            destination = Path(directory) / "report.part"
            session.capture_report(
                "page_1",
                destination,
                allowed_domains={"example.test"},
                max_bytes=1024,
            )
            self.assertEqual(destination.read_bytes(), b"%PDF-1.7\nreport")

    def test_current_pdf_navigation_response_is_captured_without_refetch(self) -> None:
        session = BrowserSession(
            BrowserSessionConfig(),
            resolver=lambda _host, _port: ["93.184.216.34"],
        )
        response = _Response(b"%PDF-1.7\npost response")
        session._last_document_response = response  # type: ignore[attr-defined]

        self.assertEqual(session.current_document_media_type, "application/pdf")
        with TemporaryDirectory() as directory:
            destination = Path(directory) / "report.part"
            session.capture_report(
                "page_1",
                destination,
                allowed_domains={"example.test"},
                max_bytes=1024,
            )
            self.assertEqual(destination.read_bytes(), b"%PDF-1.7\npost response")

    def test_trusted_html_report_can_be_printed_to_pdf(self) -> None:
        session = BrowserSession(
            BrowserSessionConfig(),
            resolver=lambda _host, _port: ["93.184.216.34"],
        )
        session._page = _Page("https://reports.example.test/report/view/123")  # type: ignore[attr-defined]

        with TemporaryDirectory() as directory:
            destination = Path(directory) / "report.part"
            session.capture_report(
                "printable_page_1",
                destination,
                allowed_domains={"example.test"},
                max_bytes=1024,
            )

            self.assertTrue(destination.read_bytes().startswith(b"%PDF"))

    def test_bounded_post_login_wait_retains_delayed_download(self) -> None:
        session = BrowserSession(BrowserSessionConfig())
        page = _Page()
        download = _Download()
        page.wait_callback = (
            lambda: session._handle_download(download)  # type: ignore[attr-defined]
        )
        session._page = page  # type: ignore[attr-defined]

        session.wait(1.0, capture_report_events=True)

        self.assertTrue(session.has_pending_report_download)
        self.assertFalse(download.cancelled)


if __name__ == "__main__":
    unittest.main()
