"""Validated Phase 5 browser tools and deterministic candidate ranking."""

from dataclasses import dataclass
import re
from typing import Protocol
from urllib.parse import urlsplit

from browser_agent.download_manager import ReportDownloadManager
from browser_agent.errors import (
    BrowserTimeoutError,
    ElementUnavailableError,
    InteractionSafetyError,
    PageInspectionError,
)
from browser_agent.field_matcher import DocumentFieldStore
from browser_agent.inspector import PageInspector
from browser_agent.models import (
    AgentAction,
    AgentActionType,
    AuthenticationSignals,
    BrowserObservation,
    ButtonSemanticAction,
    DownloadCandidate,
    DownloadCandidateKind,
    DownloadedFile,
    HtmlInputType,
    LinkPurpose,
    PageType,
    SearchObservation,
    SearchResult,
)
from browser_agent.safety import registrable_domain, validate_public_url
from browser_agent.search import DuckDuckGoSearchProvider, SearchProvider
from browser_agent.session import BrowserSession
from document_understanding.models import ConfidenceLevel
from utils.logger import get_logger


logger = get_logger(__name__)
ALLOWED_BUTTON_ACTIONS = {
    ButtonSemanticAction.LOGIN,
    ButtonSemanticAction.SUBMIT,
    ButtonSemanticAction.CONTINUE,
    ButtonSemanticAction.VIEW_REPORT,
    ButtonSemanticAction.DOWNLOAD,
}
ALLOWED_LINK_PURPOSES = {
    LinkPurpose.PATIENT_PORTAL,
    LinkPurpose.REPORTS,
    LinkPurpose.RESULTS,
    LinkPurpose.LOGIN,
    LinkPurpose.DOWNLOAD,
}


class RetrievalToolset(Protocol):
    def __enter__(self) -> "RetrievalToolset": ...

    def __exit__(self, *_: object) -> None: ...

    @property
    def current_domain(self) -> str | None: ...

    @property
    def warnings(self) -> list[str]: ...

    def open_url(self, url: str) -> BrowserObservation: ...

    def search_web(self, query: str) -> SearchObservation: ...

    def open_search_result(self, result: SearchResult) -> BrowserObservation: ...

    def inspect_page(self) -> BrowserObservation: ...

    def fill_field(self, action: AgentAction, observation: BrowserObservation) -> None: ...

    def click(self, action: AgentAction, observation: BrowserObservation) -> BrowserObservation: ...

    def wait(self, action: AgentAction) -> BrowserObservation: ...

    def go_back(self, action: AgentAction) -> BrowserObservation: ...

    def download(
        self, action: AgentAction, observation: BrowserObservation
    ) -> DownloadedFile: ...


def _tokens(value: str | None) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", (value or "").casefold())
        if len(token) > 1
    }


@dataclass(frozen=True, slots=True)
class SearchSelection:
    result: SearchResult | None
    ambiguous: bool


class SearchResultRanker:
    EXCLUDED_TERMS = {
        "facebook",
        "instagram",
        "linkedin",
        "news",
        "twitter",
        "wikipedia",
        "youtube",
        "directory",
    }

    def select(
        self, organization_name: str | None, results: list[SearchResult]
    ) -> SearchSelection:
        organization_tokens = _tokens(organization_name)
        ranked: list[tuple[float, SearchResult]] = []
        for result in results:
            combined = f"{result.title} {result.domain} {result.snippet or ''}".casefold()
            if any(term in combined for term in self.EXCLUDED_TERMS):
                continue
            result_tokens = _tokens(combined)
            overlap = len(organization_tokens & result_tokens)
            score = overlap * 2.0
            if any(term in combined for term in ("report", "result", "patient", "portal")):
                score += 2.0
            if "official" in combined:
                score += 1.0
            if result.position <= 3:
                score += 0.5
            ranked.append((score, result))
        ranked.sort(key=lambda pair: pair[0], reverse=True)
        if not ranked or ranked[0][0] < 3.5:
            return SearchSelection(result=None, ambiguous=False)
        if len(ranked) > 1 and ranked[0][0] - ranked[1][0] < 1.5:
            return SearchSelection(result=None, ambiguous=True)
        return SearchSelection(result=ranked[0][1], ambiguous=False)


class InteractionSafetyValidator:
    def __init__(self, field_store: DocumentFieldStore) -> None:
        self._field_store = field_store

    def validate_fill(
        self,
        action: AgentAction,
        observation: BrowserObservation,
        *,
        current_url: str,
        trusted_domains: set[str],
    ) -> None:
        if action.type != AgentActionType.FILL_FIELD:
            raise InteractionSafetyError("Only a structured fill action is permitted.")
        if not action.element_id or not action.document_field_ref:
            raise InteractionSafetyError("The fill action is incomplete.")
        descriptor = self._field_store.descriptor(action.document_field_ref)
        if descriptor is None:
            raise InteractionSafetyError("The document field reference does not exist.")
        page_field = next(
            (
                item
                for item in observation.input_fields
                if item.element_id == action.element_id
            ),
            None,
        )
        if page_field is None or page_field.disabled or page_field.readonly:
            raise InteractionSafetyError("The webpage field cannot be filled safely.")
        if page_field.html_type in {
            HtmlInputType.CHECKBOX,
            HtmlInputType.RADIO,
            HtmlInputType.SELECT,
            HtmlInputType.OTHER,
        }:
            raise InteractionSafetyError("This webpage field requires manual input.")

        destination = validate_public_url(current_url)
        # Every value sourced from a medical document or supplied at this boundary
        # is treated as sensitive, including dates and organization-specific fields.
        if not destination.uses_https:
            raise InteractionSafetyError(
                "Sensitive document information cannot be entered over HTTP."
            )
        if destination.domain not in trusted_domains:
            raise InteractionSafetyError(
                "Sensitive information cannot be entered on an untrusted domain."
            )

        containing_form = next(
            (
                form
                for form in observation.forms
                if action.element_id in form.input_references
            ),
            None,
        )
        if (
            containing_form
            and containing_form.action_domain
            and containing_form.action_domain not in trusted_domains
        ):
            raise InteractionSafetyError(
                "The form would send information to an untrusted domain."
            )

    @staticmethod
    def validate_click(action: AgentAction, observation: BrowserObservation) -> None:
        if action.type != AgentActionType.CLICK or not action.element_id:
            raise InteractionSafetyError("Only a structured click action is permitted.")
        button = next(
            (item for item in observation.buttons if item.element_id == action.element_id),
            None,
        )
        if button:
            if button.disabled or button.semantic_action not in ALLOWED_BUTTON_ACTIONS:
                raise InteractionSafetyError("This webpage button is not permitted.")
            return
        link = next(
            (item for item in observation.links if item.element_id == action.element_id),
            None,
        )
        if not link or link.likely_purpose not in ALLOWED_LINK_PURPOSES:
            raise InteractionSafetyError("This webpage link is not permitted.")

    @staticmethod
    def validate_download(action: AgentAction, observation: BrowserObservation) -> None:
        if action.type != AgentActionType.DOWNLOAD or not action.element_id:
            raise InteractionSafetyError("Only a structured download action is permitted.")
        if not any(
            item.element_id == action.element_id
            for item in observation.download_candidates
        ):
            raise InteractionSafetyError("The download reference was not observed.")


class ControlledBrowserTools:
    """Trusted execution layer; planners never receive raw Playwright objects."""

    def __init__(
        self,
        session: BrowserSession,
        field_store: DocumentFieldStore,
        download_manager: ReportDownloadManager,
        *,
        inspector: PageInspector | None = None,
        search_provider: SearchProvider | None = None,
    ) -> None:
        self._session = session
        self._field_store = field_store
        self._download_manager = download_manager
        self._inspector = inspector or PageInspector()
        self._search_provider = search_provider or DuckDuckGoSearchProvider()
        self._validator = InteractionSafetyValidator(field_store)
        self._trusted_domains: set[str] = set()
        self._warnings: list[str] = []

    def __enter__(self) -> "ControlledBrowserTools":
        self._session.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._session.close()

    @property
    def current_domain(self) -> str | None:
        try:
            hostname = urlsplit(self._session.current_url).hostname
            return registrable_domain(hostname.casefold()) if hostname else None
        except Exception:
            return None

    @property
    def warnings(self) -> list[str]:
        return list(dict.fromkeys([*self._warnings, *self._session.warnings]))

    def _trust_navigation(self) -> None:
        navigation = self._session.last_navigation
        if navigation:
            self._trusted_domains.update(
                {navigation.requested.domain, navigation.final.domain}
            )

    def open_url(self, url: str) -> BrowserObservation:
        try:
            self._session.open_url(url)
        except BrowserTimeoutError:
            self._warnings.append("Initial page load timed out and was retried once.")
            self._session.open_url(url)
        self._trust_navigation()
        try:
            return self.inspect_page()
        except PageInspectionError:
            self._session.wait(0.75)
            self._warnings.append(
                "The changed page was not ready and was re-inspected once."
            )
            return self.inspect_page()

    def search_web(self, query: str) -> SearchObservation:
        return self._search_provider.search(self._session, query)

    def open_search_result(self, result: SearchResult) -> BrowserObservation:
        validate_public_url(result.url)
        try:
            self._session.open_url(result.url)
        except BrowserTimeoutError:
            self._warnings.append("Search-result navigation timed out and was retried once.")
            self._session.open_url(result.url)
        self._trust_navigation()
        return self.inspect_page()

    def inspect_page(self) -> BrowserObservation:
        observation = self._inspector.inspect(self._session.page)
        media_type = self._session.current_document_media_type
        file_type = {
            "application/pdf": "pdf",
            "image/png": "png",
            "image/jpeg": "jpeg",
            "image/jpg": "jpeg",
        }.get(media_type or "")
        pending_download = self._session.has_pending_report_download
        if not file_type and pending_download:
            file_type = self._session.pending_report_file_type
        if (not file_type and not pending_download) or any(
            item.kind == DownloadCandidateKind.CURRENT_DOCUMENT
            for item in observation.download_candidates
        ):
            updated = observation.model_copy(
                update={
                    "document_media_type": media_type,
                    "pending_download_detected": pending_download,
                }
            )
            has_direct_report = any(
                item.likely_file_type in {"pdf", "png", "jpeg"}
                or item.kind
                in {
                    DownloadCandidateKind.EMBEDDED_RESOURCE,
                    DownloadCandidateKind.CURRENT_DOCUMENT,
                }
                for item in updated.download_candidates
            )
            if (
                updated.page_type == PageType.REPORT_VIEWER
                and media_type in {None, "text/html", "application/xhtml+xml"}
                and not has_direct_report
                and not any(
                    item.kind == DownloadCandidateKind.PRINTABLE_PAGE
                    for item in updated.download_candidates
                )
            ):
                printable = DownloadCandidate(
                    element_id="printable_page_1",
                    label="Printable PDF report",
                    kind=DownloadCandidateKind.PRINTABLE_PAGE,
                    likely_file_type="pdf",
                    confidence=ConfidenceLevel.HIGH,
                )
                return updated.model_copy(
                    update={
                        "download_candidates": [
                            *updated.download_candidates,
                            printable,
                        ]
                    }
                )
            return updated
        candidate = DownloadCandidate(
            element_id="page_1",
            label=(
                f"Current {file_type.upper()} report"
                if file_type
                else "Current report download"
            ),
            kind=DownloadCandidateKind.CURRENT_DOCUMENT,
            likely_file_type=file_type,
            confidence=ConfidenceLevel.HIGH,
        )
        return observation.model_copy(
            update={
                "page_type": PageType.REPORT_VIEWER,
                "document_media_type": media_type,
                "pending_download_detected": pending_download,
                "authentication_signals": AuthenticationSignals(
                    authentication_required=False,
                    field_count=0,
                    confidence=ConfidenceLevel.LOW,
                ),
                "download_candidates": [
                    *observation.download_candidates,
                    candidate,
                ],
            }
        )

    def fill_field(self, action: AgentAction, observation: BrowserObservation) -> None:
        self._validator.validate_fill(
            action,
            observation,
            current_url=self._session.current_url,
            trusted_domains=self._trusted_domains,
        )
        assert action.element_id and action.document_field_ref
        value = self._field_store.resolve(action.document_field_ref)
        try:
            self._session.fill_field(action.element_id, value)
        except ElementUnavailableError:
            refreshed = self.inspect_page()
            self._validator.validate_fill(
                action,
                refreshed,
                current_url=self._session.current_url,
                trusted_domains=self._trusted_domains,
            )
            self._warnings.append(
                "A webpage field changed and was safely re-inspected once."
            )
            self._session.fill_field(action.element_id, value)

    def click(
        self, action: AgentAction, observation: BrowserObservation
    ) -> BrowserObservation:
        self._validator.validate_click(action, observation)
        source_domain = self.current_domain
        assert action.element_id
        try:
            self._session.click(action.element_id)
        except ElementUnavailableError:
            refreshed = self.inspect_page()
            self._validator.validate_click(action, refreshed)
            self._warnings.append(
                "A webpage action changed and was safely re-inspected once."
            )
            self._session.click(action.element_id)
        destination = validate_public_url(self._session.current_url)
        if source_domain in self._trusted_domains:
            self._trusted_domains.add(destination.domain)
            if source_domain != destination.domain:
                self._warnings.append(
                    "A validated report action continued on a different public domain."
                )
        try:
            return self.inspect_page()
        except PageInspectionError:
            self._session.wait(0.75)
            self._warnings.append(
                "The changed page was not ready and was re-inspected once."
            )
            return self.inspect_page()

    def wait(self, action: AgentAction) -> BrowserObservation:
        if action.type != AgentActionType.WAIT or action.wait_seconds is None:
            raise InteractionSafetyError("Only a structured bounded wait is permitted.")
        self._session.wait(action.wait_seconds, capture_report_events=True)
        return self.inspect_page()

    def go_back(self, action: AgentAction) -> BrowserObservation:
        if action.type != AgentActionType.GO_BACK:
            raise InteractionSafetyError("Only a structured back action is permitted.")
        self._session.go_back()
        destination = validate_public_url(self._session.current_url)
        if destination.domain not in self._trusted_domains:
            raise InteractionSafetyError(
                "The browser cannot return to an untrusted workflow domain."
            )
        return self.inspect_page()

    def download(
        self, action: AgentAction, observation: BrowserObservation
    ) -> DownloadedFile:
        self._validator.validate_download(action, observation)
        destination = validate_public_url(self._session.current_url)
        if not destination.uses_https or destination.domain not in self._trusted_domains:
            raise InteractionSafetyError(
                "A report can only be downloaded from a trusted HTTPS workflow domain."
            )
        assert action.element_id
        staged = self._download_manager.staging_path()
        try:
            self._session.capture_report(
                action.element_id,
                staged,
                allowed_domains=self._trusted_domains,
                max_bytes=self._download_manager.max_bytes,
            )
        except ElementUnavailableError:
            original = next(
                item
                for item in observation.download_candidates
                if item.element_id == action.element_id
            )
            refreshed = self.inspect_page()
            matching = [
                item
                for item in refreshed.download_candidates
                if (
                    item.label,
                    item.kind,
                    item.likely_file_type,
                    item.report_date,
                )
                == (
                    original.label,
                    original.kind,
                    original.likely_file_type,
                    original.report_date,
                )
            ]
            if len(matching) != 1:
                raise InteractionSafetyError(
                    "The selected report action changed before it could be captured."
                )
            retry_action = action.model_copy(
                update={"element_id": matching[0].element_id}
            )
            self._validator.validate_download(retry_action, refreshed)
            self._warnings.append(
                "The selected report action changed and was safely re-inspected once."
            )
            self._session.capture_report(
                matching[0].element_id,
                staged,
                allowed_domains=self._trusted_domains,
                max_bytes=self._download_manager.max_bytes,
            )
        return self._download_manager.validate_report(staged)
