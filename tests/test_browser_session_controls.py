import unittest

from browser_agent.session import BrowserSession, BrowserSessionConfig


class _Download:
    def __init__(self) -> None:
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


class _Page:
    def __init__(self, url: str = "https://example.test/") -> None:
        self.url = url
        self.closed = False
        self.handlers: list[str] = []
        self.locator_value: _Locator | None = None

    def on(self, event: str, _handler: object) -> None:
        self.handlers.append(event)

    def close(self) -> None:
        self.closed = True

    def locator(self, _selector: str):
        return self.locator_value

    def wait_for_timeout(self, _milliseconds: float) -> None:
        return None

    def wait_for_load_state(self, _state: str, *, timeout: float) -> None:
        return None


class _Locator:
    def __init__(self, on_click=None) -> None:
        self.on_click = on_click

    def count(self) -> int:
        return 1

    def is_visible(self) -> bool:
        return True

    def is_enabled(self) -> bool:
        return True

    def click(self) -> None:
        if self.on_click:
            self.on_click()


class BrowserSessionControlTests(unittest.TestCase):
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
        self.assertEqual(set(popup.handlers), {"dialog", "download"})

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


if __name__ == "__main__":
    unittest.main()
