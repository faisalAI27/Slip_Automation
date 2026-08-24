"""Free browser-based search abstraction for Phase 4."""

from typing import Protocol
from urllib.parse import parse_qs, quote_plus, unquote, urlsplit

from playwright.sync_api import Error as PlaywrightError

from browser_agent.errors import SearchExecutionError
from browser_agent.models import SearchObservation, SearchResult
from browser_agent.safety import redact_url_for_display, registrable_domain
from browser_agent.session import BrowserSession
from utils.logger import get_logger


logger = get_logger(__name__)


class SearchProvider(Protocol):
    def search(self, session: BrowserSession, query: str) -> SearchObservation:
        """Execute one public search and return structured results without opening them."""
        ...


def _result_destination(value: str) -> str | None:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    if parsed.hostname and parsed.hostname.casefold().endswith("duckduckgo.com"):
        encoded = parse_qs(parsed.query).get("uddg", [None])[0]
        if encoded:
            value = unquote(encoded)
            try:
                parsed = urlsplit(value)
            except ValueError:
                return None
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.hostname:
        return None
    return value


class DuckDuckGoSearchProvider:
    provider_name = "duckduckgo_browser"

    def __init__(self, max_results: int = 8) -> None:
        self._max_results = max(1, min(max_results, 10))

    def search(self, session: BrowserSession, query: str) -> SearchObservation:
        search_url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
        session.open_url(search_url)
        page = session.page
        try:
            rows = page.locator(".result, article[data-testid='result']")
            row_count = min(rows.count(), self._max_results * 2)
            results: list[SearchResult] = []
            seen: set[str] = set()
            for index in range(row_count):
                row = rows.nth(index)
                title_link = row.locator(
                    "a.result__a, a[data-testid='result-title-a']"
                ).first
                if title_link.count() == 0:
                    continue
                title = title_link.inner_text().strip()
                raw_url = title_link.get_attribute("href") or ""
                destination = _result_destination(raw_url)
                if not title or destination is None:
                    continue
                parsed = urlsplit(destination)
                hostname = (parsed.hostname or "").casefold()
                domain = registrable_domain(hostname)
                key = redact_url_for_display(destination).casefold()
                if key in seen:
                    continue
                seen.add(key)
                snippets = row.locator(
                    ".result__snippet, [data-result='snippet'], [data-testid='result-snippet']"
                )
                snippet = (
                    snippets.first.inner_text().strip()[:500]
                    if snippets.count()
                    else None
                )
                results.append(
                    SearchResult(
                        title=title[:300],
                        url=destination,
                        domain=domain,
                        snippet=snippet or None,
                        position=len(results) + 1,
                    )
                )
                if len(results) >= self._max_results:
                    break
        except PlaywrightError as exc:
            raise SearchExecutionError("Public search results could not be inspected.") from exc

        body_text = ""
        try:
            body_text = page.locator("body").inner_text().casefold()
        except PlaywrightError:
            pass
        if not results and any(
            term in body_text
            for term in (
                "captcha",
                "blocked",
                "robot",
                "bots use duckduckgo",
                "complete the following challenge",
                "squares containing a duck",
            )
        ):
            raise SearchExecutionError(
                "The free search provider blocked automated access."
            )

        if not results:
            raise SearchExecutionError(
                "The free search provider returned no usable public results."
            )
        logger.info("Search completed with %d candidates", len(results))
        return SearchObservation(
            query=query,
            provider=self.provider_name,
            results=results,
            warnings=[],
        )
