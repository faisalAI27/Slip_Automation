"""Controlled browser-tool contracts reserved for current and future phases."""

from enum import Enum
from typing import Protocol

from browser_agent.models import BrowserObservation, SearchObservation
from browser_agent.session import NavigationOutcome


class BrowserToolName(str, Enum):
    OPEN_URL = "open_url"
    SEARCH_WEB = "search_web"
    INSPECT_PAGE = "inspect_page"
    FILL_FIELD = "fill_field"
    CLICK = "click"
    GO_BACK = "go_back"
    WAIT = "wait"
    DOWNLOAD = "download"


PHASE4_EXECUTABLE_TOOLS = frozenset(
    {
        BrowserToolName.OPEN_URL,
        BrowserToolName.SEARCH_WEB,
        BrowserToolName.INSPECT_PAGE,
    }
)


class Phase4BrowserToolInterface(Protocol):
    """Only these operations may be reachable from the Phase 4 application flow."""

    def open_url(self, url: str) -> NavigationOutcome: ...

    def search_web(self, query: str) -> SearchObservation: ...

    def inspect_page(self) -> BrowserObservation: ...


class FutureBrowserInteractionInterface(Protocol):
    """Phase 5 contract only; Phase 4 provides no concrete implementation."""

    def fill_field(self, element_id: str, value: str) -> None: ...

    def click(self, element_id: str) -> None: ...

    def go_back(self) -> None: ...

    def wait(self, timeout_seconds: float) -> None: ...

    def download(self, element_id: str) -> None: ...
