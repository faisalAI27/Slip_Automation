"""Strict structured models produced by controlled Phase 4 execution."""

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from document_understanding.models import ConfidenceLevel
from workflow.models import ActionType


class StrictBrowserModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class PageType(str, Enum):
    ORGANIZATION_HOMEPAGE = "organization_homepage"
    REPORT_LOGIN_PAGE = "report_login_page"
    PATIENT_PORTAL = "patient_portal"
    REPORT_LIST_PAGE = "report_list_page"
    REPORT_VIEWER = "report_viewer"
    SEARCH_RESULTS = "search_results"
    VERIFICATION_PAGE = "verification_page"
    ERROR_PAGE = "error_page"
    UNKNOWN = "unknown"


class HtmlInputType(str, Enum):
    TEXT = "text"
    PASSWORD = "password"
    EMAIL = "email"
    NUMBER = "number"
    DATE = "date"
    TEL = "tel"
    SELECT = "select"
    CHECKBOX = "checkbox"
    RADIO = "radio"
    TEXTAREA = "textarea"
    OTHER = "other"


class ButtonSemanticAction(str, Enum):
    SUBMIT = "submit"
    LOGIN = "login"
    CONTINUE = "continue"
    VIEW_REPORT = "view_report"
    DOWNLOAD = "download"
    SEARCH = "search"
    UNKNOWN = "unknown"


class LinkPurpose(str, Enum):
    REPORTS = "reports"
    PATIENT_PORTAL = "patient_portal"
    LOGIN = "login"
    RESULTS = "results"
    DOWNLOAD = "download"
    HOME = "home"
    SUPPORT = "support"
    UNKNOWN = "unknown"


class DownloadCandidateKind(str, Enum):
    LINK = "link"
    BUTTON = "button"
    REPORT_ROW = "report_row"


class FormObservation(StrictBrowserModel):
    element_id: str = Field(pattern=r"^form_\d+$")
    name: str | None = None
    method: str | None = None
    action_domain: str | None = None
    input_references: list[str]


class InputFieldObservation(StrictBrowserModel):
    element_id: str = Field(pattern=r"^input_\d+$")
    html_type: HtmlInputType
    name: str | None = None
    label: str | None = None
    placeholder: str | None = None
    aria_label: str | None = None
    required: bool
    disabled: bool
    readonly: bool
    autocomplete: str | None = None


class ButtonObservation(StrictBrowserModel):
    element_id: str = Field(pattern=r"^button_\d+$")
    text: str | None = None
    html_type: str | None = None
    disabled: bool
    semantic_action: ButtonSemanticAction


class LinkObservation(StrictBrowserModel):
    element_id: str = Field(pattern=r"^link_\d+$")
    text: str | None = None
    url: str
    domain: str | None = None
    same_domain: bool
    likely_purpose: LinkPurpose


class DownloadCandidate(StrictBrowserModel):
    element_id: str
    label: str = Field(min_length=1)
    kind: DownloadCandidateKind
    likely_file_type: str | None = None
    confidence: ConfidenceLevel


class AuthenticationSignals(StrictBrowserModel):
    authentication_required: bool
    field_count: int = Field(ge=0)
    confidence: ConfidenceLevel


class VerificationSignals(StrictBrowserModel):
    otp_detected: bool
    captcha_detected: bool
    email_verification_detected: bool
    verification_required: bool


class RedirectRecord(StrictBrowserModel):
    from_url: str
    to_url: str
    domain_changed: bool


class SearchResult(StrictBrowserModel):
    title: str = Field(min_length=1)
    url: str
    domain: str
    snippet: str | None = None
    position: int = Field(ge=1)


class SearchObservation(StrictBrowserModel):
    query: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    results: list[SearchResult]
    warnings: list[str]


class BrowserObservation(StrictBrowserModel):
    final_url: str
    final_domain: str | None
    page_title: str | None
    page_type: PageType
    visible_text_summary: str | None
    forms: list[FormObservation]
    input_fields: list[InputFieldObservation]
    buttons: list[ButtonObservation]
    links: list[LinkObservation]
    download_candidates: list[DownloadCandidate]
    authentication_signals: AuthenticationSignals
    verification_signals: VerificationSignals
    errors_or_messages: list[str]
    warnings: list[str]
    content_is_untrusted: bool = True


class BrowserActionResult(StrictBrowserModel):
    action_type: ActionType
    success: bool
    requested_target_type: str
    requested_target: str | None = None
    final_url: str | None = None
    final_domain: str | None = None
    redirect_occurred: bool
    redirects: list[RedirectRecord]
    observation: BrowserObservation | None = None
    search_observation: SearchObservation | None = None
    warnings: list[str]
    error_type: str | None = None
    error_message: str | None = None

    @model_validator(mode="after")
    def validate_result_shape(self) -> "BrowserActionResult":
        if self.success:
            if self.error_type or self.error_message:
                raise ValueError("Successful browser results cannot contain an error.")
            if self.action_type == ActionType.OPEN_URL and self.observation is None:
                raise ValueError("OPEN_URL success requires a browser observation.")
            if self.action_type == ActionType.SEARCH_WEB and (
                self.search_observation is None or self.observation is None
            ):
                raise ValueError(
                    "SEARCH_WEB success requires search and page observations."
                )
        elif not self.error_type or not self.error_message:
            raise ValueError("Failed browser results require a controlled error.")
        return self
