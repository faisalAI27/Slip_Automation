"""Reusable isolated Playwright Chromium session for controlled navigation."""

from dataclasses import dataclass
from urllib.parse import urlsplit

from playwright.sync_api import (
    Browser,
    BrowserContext,
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
                accept_downloads=False,
                service_workers="block",
            )
            self._context.set_default_timeout(self._config.timeout_seconds * 1_000)
            self._context.set_default_navigation_timeout(
                self._config.navigation_timeout_seconds * 1_000
            )
            self._context.route("**/*", self._route_request)
            self._context.on("page", self._handle_new_page)
            self._page = self._context.new_page()
            self._page.on("dialog", lambda dialog: dialog.dismiss())
            self._page.on("download", self._handle_download)
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
        self._warnings.append("An unsolicited popup was closed without interaction.")
        try:
            page.close()
        except PlaywrightError:
            pass

    def _handle_download(self, download: object) -> None:
        self._warnings.append("A webpage-initiated download was blocked in Phase 4.")
        try:
            download.cancel()  # type: ignore[attr-defined]
        except PlaywrightError:
            pass

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
        logger.info("Browser session closed")
