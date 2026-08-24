"""Reusable isolated Playwright Chromium session for controlled navigation."""

from dataclasses import dataclass
from pathlib import Path
import re
from urllib.parse import urlsplit

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Download,
    Error as PlaywrightError,
    Page,
    Playwright,
    Route,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

from browser_agent.errors import (
    BrowserConfigurationError,
    BrowserLaunchError,
    BrowserTimeoutError,
    DownloadCaptureError,
    ElementUnavailableError,
    InteractionSafetyError,
    NavigationError,
    UnsafeNavigationError,
)
from browser_agent.models import RedirectRecord
from browser_agent.safety import (
    AddressResolver,
    ValidatedURL,
    redact_url_for_display,
    validate_public_url,
)
from utils.logger import get_logger


logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class BrowserSessionConfig:
    headless: bool = True
    timeout_seconds: float = 30.0
    navigation_timeout_seconds: float = 45.0


@dataclass(frozen=True, slots=True)
class NavigationOutcome:
    requested: ValidatedURL
    final: ValidatedURL
    redirects: list[RedirectRecord]
    status_code: int | None
    warnings: list[str]


class BrowserSession:
    """Own a non-persistent context that can support later sequential actions."""

    def __init__(
        self,
        config: BrowserSessionConfig,
        *,
        resolver: AddressResolver | None = None,
    ) -> None:
        self._config = config
        self._resolver = resolver
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._verified_hosts: set[tuple[str, int]] = set()
        self._blocked_error: UnsafeNavigationError | None = None
        self._warnings: list[str] = []
        self._last_navigation: NavigationOutcome | None = None
        self._expected_download = False
        self._expected_popup = False
        self._pending_popup: Page | None = None

    @property
    def page(self) -> Page:
        if self._page is None:
            raise BrowserLaunchError("The browser page is not available.")
        return self._page

    @property
    def warnings(self) -> list[str]:
        return list(dict.fromkeys(self._warnings))

    @property
    def last_navigation(self) -> NavigationOutcome | None:
        return self._last_navigation

    @property
    def current_url(self) -> str:
        return self.page.url

    def __enter__(self) -> "BrowserSession":
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _validate(self, value: str, *, resolve_dns: bool = True) -> ValidatedURL:
        if self._resolver is not None:
            return validate_public_url(
                value,
                resolver=self._resolver,
                resolve_dns=resolve_dns,
            )
        return validate_public_url(value, resolve_dns=resolve_dns)

    def start(self) -> None:
        if self._playwright is not None:
            return
        try:
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(
                headless=self._config.headless
            )
            self._context = self._browser.new_context(
                accept_downloads=True,
                service_workers="block",
            )
            self._context.set_default_timeout(self._config.timeout_seconds * 1_000)
            self._context.set_default_navigation_timeout(
                self._config.navigation_timeout_seconds * 1_000
            )
            self._context.route("**/*", self._route_request)
            self._context.on("page", self._handle_new_page)
            self._page = self._context.new_page()
            self._prepare_page(self._page)
        except PlaywrightError as exc:
            self.close()
            message = str(exc).casefold()
            if "executable doesn't exist" in message or "playwright install" in message:
                raise BrowserConfigurationError(
                    "Chromium is not installed for the browser layer."
                ) from exc
            raise BrowserLaunchError("Chromium could not be launched.") from exc
        logger.info("Browser session started")

    def _route_request(self, route: Route) -> None:
        request = route.request
        parsed = urlsplit(request.url)
        scheme = parsed.scheme.casefold()
        if scheme not in {"http", "https"}:
            if not request.is_navigation_request() and scheme in {
                "about",
                "blob",
                "data",
            }:
                route.continue_()
                return
            self._blocked_error = UnsafeNavigationError(
                "A non-HTTP(S) browser request was blocked."
            )
            route.abort("blockedbyclient")
            return

        try:
            shaped = self._validate(request.url, resolve_dns=False)
            host_key = (shaped.hostname, shaped.port)
            if host_key not in self._verified_hosts:
                self._validate(request.url, resolve_dns=True)
                self._verified_hosts.add(host_key)
        except UnsafeNavigationError as exc:
            self._blocked_error = exc
            route.abort("blockedbyclient")
            return
        route.continue_()

    def _handle_new_page(self, page: Page) -> None:
        if self._page is None or page == self._page:
            return
        if self._expected_popup:
            self._pending_popup = page
            self._prepare_page(page)
            return
        self._warnings.append("An unsolicited popup was closed without interaction.")
        try:
            page.close()
        except PlaywrightError:
            pass

    def _handle_download(self, download: Download) -> None:
        if self._expected_download:
            return
        self._warnings.append("An unsolicited webpage download was blocked.")
        try:
            download.cancel()
        except PlaywrightError:
            pass

    def _prepare_page(self, page: Page) -> None:
        page.on("dialog", lambda dialog: dialog.dismiss())
        page.on("download", self._handle_download)

    def _referenced_locator(self, element_id: str) -> object:
        if not re.fullmatch(r"(?:input|button|link)_\d+", element_id):
            raise InteractionSafetyError("The browser element reference is invalid.")
        locator = self.page.locator(f'[data-slip-ref="{element_id}"]')
        try:
            if locator.count() != 1:
                raise ElementUnavailableError(
                    "The referenced webpage element is no longer available."
                )
            if not locator.is_visible() or not locator.is_enabled():
                raise ElementUnavailableError(
                    "The referenced webpage element cannot be used safely."
                )
        except PlaywrightError as exc:
            raise ElementUnavailableError(
                "The referenced webpage element could not be checked."
            ) from exc
        return locator

    def fill_field(self, element_id: str, value: str) -> None:
        locator = self._referenced_locator(element_id)
        try:
            if locator.is_editable() is False:  # type: ignore[attr-defined]
                raise ElementUnavailableError(
                    "The referenced webpage field is not editable."
                )
            locator.fill(value)  # type: ignore[attr-defined]
        except ElementUnavailableError:
            raise
        except PlaywrightError as exc:
            raise ElementUnavailableError(
                "The referenced webpage field could not be filled."
            ) from exc
        logger.info("Controlled field fill completed")

    def click(self, element_id: str) -> None:
        locator = self._referenced_locator(element_id)
        self._expected_popup = True
        self._pending_popup = None
        try:
            locator.click()  # type: ignore[attr-defined]
            self.page.wait_for_timeout(250)
        except PlaywrightTimeoutError as exc:
            raise BrowserTimeoutError("The webpage action took too long.") from exc
        except PlaywrightError as exc:
            raise ElementUnavailableError(
                "The referenced webpage action could not be completed."
            ) from exc
        finally:
            self._expected_popup = False

        if self._pending_popup is not None:
            popup = self._pending_popup
            self._pending_popup = None
            try:
                popup.wait_for_load_state(
                    "domcontentloaded",
                    timeout=self._config.navigation_timeout_seconds * 1_000,
                )
            except PlaywrightTimeoutError:
                self._warnings.append(
                    "The expected report popup did not finish loading before inspection."
                )
            validated = self._validate(popup.url)
            self._page = popup
            self._verified_hosts.add((validated.hostname, validated.port))
        else:
            parsed = urlsplit(self.page.url)
            if parsed.scheme.casefold() in {"http", "https"}:
                self._validate(self.page.url)
        logger.info("Controlled webpage click completed")

    def capture_download(self, element_id: str, destination: Path) -> None:
        locator = self._referenced_locator(element_id)
        self._expected_download = True
        try:
            with self.page.expect_download(
                timeout=self._config.navigation_timeout_seconds * 1_000
            ) as download_info:
                locator.click()  # type: ignore[attr-defined]
            download = download_info.value
            download.save_as(str(destination))
        except PlaywrightTimeoutError as exc:
            raise DownloadCaptureError(
                "The validated report action did not produce a download."
            ) from exc
        except PlaywrightError as exc:
            raise DownloadCaptureError(
                "The expected report download could not be captured."
            ) from exc
        finally:
            self._expected_download = False
        logger.info("Controlled report download captured")

    def wait(self, timeout_seconds: float) -> None:
        bounded = max(0.0, min(timeout_seconds, 30.0))
        try:
            self.page.wait_for_timeout(bounded * 1_000)
        except PlaywrightError as exc:
            raise BrowserTimeoutError("The controlled browser wait failed.") from exc

    def go_back(self) -> None:
        try:
            self.page.go_back(
                wait_until="domcontentloaded",
                timeout=self._config.navigation_timeout_seconds * 1_000,
            )
            self._validate(self.page.url)
        except PlaywrightTimeoutError as exc:
            raise BrowserTimeoutError("The browser could not return safely.") from exc
        except PlaywrightError as exc:
            raise NavigationError("The browser could not return safely.") from exc

    @staticmethod
    def _redirect_urls(response: object, final_url: str, requested_url: str) -> list[str]:
        chain: list[str] = []
        try:
            request = response.request if response is not None else None  # type: ignore[attr-defined]
            while request is not None:
                chain.append(request.url)
                request = request.redirected_from
            chain.reverse()
        except (AttributeError, PlaywrightError):
            chain = []
        if not chain:
            chain.append(requested_url)
        if chain[-1] != final_url:
            chain.append(final_url)
        return list(dict.fromkeys(chain))

    def open_url(self, value: str) -> NavigationOutcome:
        requested = self._validate(value)
        if self._page is None:
            raise BrowserLaunchError("The browser page is not available.")
        self._blocked_error = None
        warnings: list[str] = []
        if not requested.uses_https:
            warnings.append("The destination uses an unencrypted HTTP connection.")

        try:
            response = self._page.goto(
                requested.url,
                wait_until="domcontentloaded",
                timeout=self._config.navigation_timeout_seconds * 1_000,
            )
            if self._blocked_error is not None:
                raise self._blocked_error
            try:
                self._page.locator("body").wait_for(
                    state="visible",
                    timeout=min(self._config.timeout_seconds, 3.0) * 1_000,
                )
            except PlaywrightTimeoutError:
                warnings.append(
                    "The page body did not become visibly ready before inspection."
                )
        except PlaywrightTimeoutError as exc:
            raise BrowserTimeoutError("The website took too long to respond.") from exc
        except UnsafeNavigationError:
            raise
        except PlaywrightError as exc:
            if self._blocked_error is not None:
                raise self._blocked_error from exc
            raise NavigationError("The website could not be opened.") from exc

        final = self._validate(self._page.url)
        chain = self._redirect_urls(response, final.url, requested.url)
        redirects: list[RedirectRecord] = []
        for from_url, to_url in zip(chain, chain[1:], strict=False):
            from_destination = self._validate(from_url)
            to_destination = self._validate(to_url)
            domain_changed = from_destination.domain != to_destination.domain
            redirects.append(
                RedirectRecord(
                    from_url=redact_url_for_display(from_url),
                    to_url=redact_url_for_display(to_url),
                    domain_changed=domain_changed,
                )
            )
            if domain_changed:
                warnings.append("Navigation redirected to a different public domain.")

        status_code = None
        try:
            status_code = response.status if response is not None else None
        except AttributeError:
            pass
        logger.info("Browser navigation completed")
        outcome = NavigationOutcome(
            requested=requested,
            final=final,
            redirects=redirects,
            status_code=status_code,
            warnings=list(dict.fromkeys([*warnings, *self._warnings])),
        )
        self._last_navigation = outcome
        return outcome

    def close(self) -> None:
        if self._context is not None:
            try:
                self._context.close()
            except PlaywrightError:
                pass
        if self._browser is not None:
            try:
                self._browser.close()
            except PlaywrightError:
                pass
        if self._playwright is not None:
            try:
                self._playwright.stop()
            except PlaywrightError:
                pass
        self._page = None
        self._context = None
        self._browser = None
        self._playwright = None
        self._verified_hosts.clear()
        self._last_navigation = None
        self._expected_download = False
        self._expected_popup = False
        self._pending_popup = None
        logger.info("Browser session closed")
