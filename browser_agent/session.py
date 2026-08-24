"""Reusable isolated Playwright Chromium session for controlled navigation."""

from dataclasses import dataclass, field
from pathlib import Path
import re
from urllib.parse import urljoin, urlsplit, urlunsplit

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Download,
    Error as PlaywrightError,
    Page,
    Playwright,
    Route,
    Response,
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
    navigation_url_rewrites: dict[str, str] = field(default_factory=dict)


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
        self._last_document_response: Response | None = None
        self._pending_download: Download | None = None
        self._navigation_url_rewrites = {
            str(host).strip().rstrip(".").casefold(): str(origin).strip()
            for host, origin in config.navigation_url_rewrites.items()
            if str(host).strip() and str(origin).strip()
        }

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

    @property
    def current_document_media_type(self) -> str | None:
        response = self._last_document_response
        if response is None:
            return None
        try:
            value = response.headers.get("content-type", "")
        except (AttributeError, PlaywrightError):
            return None
        media_type = value.split(";", 1)[0].strip().casefold()
        return media_type or None

    @property
    def has_pending_report_download(self) -> bool:
        return self._pending_download is not None

    @property
    def pending_report_file_type(self) -> str | None:
        if self._pending_download is None:
            return None
        try:
            filename = self._pending_download.suggested_filename.casefold()
        except (AttributeError, PlaywrightError):
            return None
        if filename.endswith(".pdf"):
            return "pdf"
        if filename.endswith(".png"):
            return "png"
        if filename.endswith((".jpg", ".jpeg")):
            return "jpeg"
        return None

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
            rewritten = self._configured_https_rewrite(request.url)
        except UnsafeNavigationError as exc:
            self._blocked_error = exc
            route.abort("blockedbyclient")
            return
        if rewritten is not None:
            if not request.is_navigation_request() or request.method.casefold() != "get":
                self._blocked_error = UnsafeNavigationError(
                    "An insecure portal request could not be upgraded safely."
                )
                route.abort("blockedbyclient")
                return
            try:
                validated_rewrite = self._validate(rewritten)
            except UnsafeNavigationError as exc:
                self._blocked_error = exc
                route.abort("blockedbyclient")
                return
            self._warnings.append(
                "An insecure portal redirect was upgraded to its configured HTTPS origin."
            )
            route.fulfill(
                status=307,
                headers={
                    "location": validated_rewrite.url,
                    "cache-control": "no-store",
                },
                body="",
            )
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

    def _configured_https_rewrite(self, value: str) -> str | None:
        parsed = urlsplit(value)
        hostname = (parsed.hostname or "").rstrip(".").casefold()
        if parsed.scheme.casefold() != "http" or not hostname:
            return None
        configured = self._navigation_url_rewrites.get(hostname)
        if not configured:
            return None
        target = urlsplit(configured)
        if (
            target.scheme.casefold() != "https"
            or not target.hostname
            or target.username
            or target.password
            or target.query
            or target.fragment
        ):
            raise UnsafeNavigationError(
                "The configured portal HTTPS rewrite is invalid."
            )
        base_path = target.path.rstrip("/")
        requested_path = parsed.path or "/"
        path = (
            f"{base_path}/{requested_path.lstrip('/')}"
            if base_path
            else requested_path
        )
        return urlunsplit(
            ("https", target.netloc, path, parsed.query, "")
        )

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
            self._pending_download = download
            return
        self._warnings.append("An unsolicited webpage download was blocked.")
        try:
            download.cancel()
        except PlaywrightError:
            pass

    def _prepare_page(self, page: Page) -> None:
        page.on("dialog", lambda dialog: dialog.dismiss())
        page.on("download", self._handle_download)
        page.on("response", lambda response: self._handle_response(page, response))

    def _handle_response(self, page: Page, response: Response) -> None:
        try:
            if (
                response.request.resource_type == "document"
                and response.frame == page.main_frame
            ):
                self._last_document_response = response
        except PlaywrightError:
            return

    def _referenced_locator(self, element_id: str) -> object:
        if not re.fullmatch(r"(?:input|button|link|resource)_\d+", element_id):
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
        self._expected_download = True
        self._pending_popup = None
        self._pending_download = None
        try:
            locator.click()  # type: ignore[attr-defined]
            self.page.wait_for_timeout(500)
        except PlaywrightTimeoutError as exc:
            raise BrowserTimeoutError("The webpage action took too long.") from exc
        except PlaywrightError as exc:
            raise ElementUnavailableError(
                "The referenced webpage action could not be completed."
            ) from exc
        finally:
            self._expected_popup = False
            self._expected_download = False

        if not self._adopt_pending_popup():
            parsed = urlsplit(self.page.url)
            if parsed.scheme.casefold() in {"http", "https"}:
                self._validate(self.page.url)
        logger.info("Controlled webpage click completed")

    def _adopt_pending_popup(self) -> bool:
        if self._pending_popup is None:
            return False
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
        return True

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

    def capture_report(
        self,
        element_id: str,
        destination: Path,
        *,
        allowed_domains: set[str],
        max_bytes: int,
    ) -> None:
        """Capture a normal download or fetch an observed embedded report resource."""
        if element_id == "printable_page_1":
            current = self._validate(self.page.url)
            if not current.uses_https or current.domain not in allowed_domains:
                raise InteractionSafetyError(
                    "The printable report page is outside the trusted HTTPS workflow."
                )
            try:
                self.page.emulate_media(media="print")
                self.page.pdf(
                    path=str(destination),
                    format="A4",
                    print_background=True,
                    prefer_css_page_size=True,
                )
                if destination.stat().st_size > max_bytes:
                    raise DownloadCaptureError(
                        "The printable report exceeds the size limit."
                    )
            except DownloadCaptureError:
                raise
            except (OSError, PlaywrightError) as exc:
                raise DownloadCaptureError(
                    "The HTML report could not be saved as a PDF."
                ) from exc
            logger.info("Controlled HTML report captured as PDF")
            return
        if element_id == "page_1":
            if self._pending_download is not None:
                try:
                    self._pending_download.save_as(str(destination))
                except PlaywrightError as exc:
                    raise DownloadCaptureError(
                        "The report download could not be saved."
                    ) from exc
                finally:
                    self._pending_download = None
                logger.info("Controlled report download from validated action captured")
                return
            response = self._last_document_response
            if response is None:
                raise DownloadCaptureError(
                    "The final report response is no longer available."
                )
            try:
                validated = self._validate(response.url)
                if not validated.uses_https or validated.domain not in allowed_domains:
                    raise InteractionSafetyError(
                        "The final report response is outside the trusted HTTPS workflow."
                    )
                body = response.body()
                if not body or len(body) > max_bytes:
                    raise DownloadCaptureError(
                        "The final report response is empty or exceeds the size limit."
                    )
                destination.write_bytes(body)
            except (InteractionSafetyError, DownloadCaptureError):
                raise
            except (OSError, PlaywrightError) as exc:
                raise DownloadCaptureError(
                    "The final report response could not be captured."
                ) from exc
            logger.info("Controlled final report response captured")
            return

        locator = self._referenced_locator(element_id)
        try:
            resource = locator.evaluate(
                """
                (element) => {
                  const tag = element.tagName.toLowerCase();
                  const raw = tag === "object"
                    ? element.data
                    : tag === "a"
                    ? element.href
                    : element.src;
                  return {
                    tag,
                    url: raw || null,
                    download: tag === "a" && element.hasAttribute("download"),
                  };
                }
                """
            )
        except PlaywrightError as exc:
            raise DownloadCaptureError(
                "The observed report resource could not be checked."
            ) from exc

        direct_url = resource.get("url") if isinstance(resource, dict) else None
        tag = resource.get("tag") if isinstance(resource, dict) else None
        direct_tags = {"embed", "object", "iframe", "img"}
        should_fetch = bool(direct_url) and (
            tag in direct_tags or bool(resource.get("download"))
            or bool(re.search(r"\.(?:pdf|png|jpe?g)(?:[?#]|$)", str(direct_url), re.I))
        )
        if not should_fetch:
            self.capture_download(element_id, destination)
            return

        resource_url = str(direct_url)
        rewritten = self._configured_https_rewrite(resource_url)
        if rewritten is not None:
            resource_url = rewritten
            self._warnings.append(
                "An insecure report resource URL was upgraded to its configured "
                "HTTPS origin."
            )
        validated = self._validate(resource_url)
        if not validated.uses_https or validated.domain not in allowed_domains:
            raise InteractionSafetyError(
                "The embedded report resource is outside the trusted HTTPS workflow."
            )
        if self._context is None:
            raise DownloadCaptureError("The private browser context is unavailable.")
        try:
            response = None
            current = validated
            for redirect_count in range(4):
                response = self._context.request.get(
                    current.url,
                    timeout=self._config.navigation_timeout_seconds * 1_000,
                    max_redirects=0,
                )
                if response.status not in {301, 302, 303, 307, 308}:
                    break
                if redirect_count == 3:
                    raise DownloadCaptureError(
                        "The report resource redirected too many times."
                    )
                location = response.headers.get("location")
                if not location:
                    raise DownloadCaptureError(
                        "The report resource returned an incomplete redirect."
                    )
                next_url = urljoin(current.url, location)
                rewritten = self._configured_https_rewrite(next_url)
                if rewritten is not None:
                    next_url = rewritten
                    self._warnings.append(
                        "An insecure report resource redirect was upgraded to its "
                        "configured HTTPS origin."
                    )
                current = self._validate(next_url)
                if not current.uses_https or current.domain not in allowed_domains:
                    raise InteractionSafetyError(
                        "The report resource redirected outside the trusted HTTPS "
                        "workflow."
                    )
            if response is None:
                raise DownloadCaptureError(
                    "The observed report resource could not be downloaded."
                )
            final = self._validate(response.url)
            if final.domain not in allowed_domains or not final.uses_https:
                raise InteractionSafetyError(
                    "The report resource redirected outside the trusted HTTPS workflow."
                )
            if not response.ok:
                raise DownloadCaptureError(
                    "The observed report resource could not be downloaded."
                )
            content_length = response.headers.get("content-length")
            if content_length and int(content_length) > max_bytes:
                raise DownloadCaptureError("The report resource exceeds the size limit.")
            body = response.body()
            if not body or len(body) > max_bytes:
                raise DownloadCaptureError(
                    "The report resource is empty or exceeds the size limit."
                )
            destination.write_bytes(body)
        except (InteractionSafetyError, DownloadCaptureError):
            raise
        except (OSError, PlaywrightError, ValueError) as exc:
            raise DownloadCaptureError(
                "The observed report resource could not be captured."
            ) from exc
        logger.info("Controlled embedded report resource captured")

    def wait(
        self,
        timeout_seconds: float,
        *,
        capture_report_events: bool = False,
    ) -> None:
        bounded = max(0.0, min(timeout_seconds, 30.0))
        if capture_report_events:
            self._expected_popup = True
            self._expected_download = True
        try:
            self.page.wait_for_timeout(bounded * 1_000)
        except PlaywrightError as exc:
            raise BrowserTimeoutError("The controlled browser wait failed.") from exc
        finally:
            if capture_report_events:
                self._expected_popup = False
                self._expected_download = False
        if capture_report_events:
            self._adopt_pending_popup()

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
        self._last_document_response = None
        self._pending_download = None
        logger.info("Browser session closed")
