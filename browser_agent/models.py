"""Strict structured models produced by controlled Phase 4 execution."""

from datetime import date
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
    EMBEDDED_RESOURCE = "embedded_resource"
    CURRENT_DOCUMENT = "current_document"
    PRINTABLE_PAGE = "printable_page"


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
    form_reference: str | None = None
    report_date: date | None = None


class LinkObservation(StrictBrowserModel):
    element_id: str = Field(pattern=r"^link_\d+$")
    text: str | None = None
    url: str
    domain: str | None = None
    same_domain: bool
    likely_purpose: LinkPurpose
    report_date: date | None = None


class DownloadCandidate(StrictBrowserModel):
    element_id: str
    label: str = Field(min_length=1)
    kind: DownloadCandidateKind
    likely_file_type: str | None = None
    confidence: ConfidenceLevel
    report_date: date | None = None


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
    embedded_resource_count: int = Field(default=0, ge=0)
    document_media_type: str | None = None
    pending_download_detected: bool = False
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


class AgentActionType(str, Enum):
    OPEN_URL = "open_url"
    SEARCH_WEB = "search_web"
    OPEN_SEARCH_RESULT = "open_search_result"
    FILL_FIELD = "fill_field"
    CLICK = "click"
    WAIT = "wait"
    GO_BACK = "go_back"
    DOWNLOAD = "download"
    REQUEST_USER_INPUT = "request_user_input"
    COMPLETE = "complete"
    STOP = "stop"


class RetrievalStatus(str, Enum):
    DOWNLOADED = "downloaded"
    USER_INPUT_REQUIRED = "user_input_required"
    VERIFICATION_REQUIRED = "verification_required"
    REPORT_NOT_FOUND = "report_not_found"
    AMBIGUOUS = "ambiguous"
    UNSUPPORTED = "unsupported"
    FAILED = "failed"


class SafeDocumentField(StrictBrowserModel):
    ref: str = Field(pattern=r"^doc_field_\d+$")
    label: str | None = None
    semantic_type: str = Field(min_length=1)
    confidence: ConfidenceLevel


class FieldMatch(StrictBrowserModel):
    document_field_ref: str = Field(pattern=r"^doc_field_\d+$")
    document_label: str | None = None
    document_semantic_type: str = Field(min_length=1)
    input_element_id: str = Field(pattern=r"^input_\d+$")
    page_field_label: str | None = None
    confidence: ConfidenceLevel


class FieldMappingResult(StrictBrowserModel):
    matches: list[FieldMatch]
    unmatched_required_inputs: list[str]
    ambiguous_input_references: list[str]

    @property
    def actionable(self) -> bool:
        return not self.unmatched_required_inputs and not self.ambiguous_input_references


class AgentAction(StrictBrowserModel):
    type: AgentActionType
    element_id: str | None = None
    document_field_ref: str | None = None
    search_result_position: int | None = Field(default=None, ge=1)
    wait_seconds: float | None = Field(default=None, ge=0, le=30)
    reason: str = Field(min_length=1)
    confidence: ConfidenceLevel

    @model_validator(mode="after")
    def validate_action_payload(self) -> "AgentAction":
        element_actions = {
            AgentActionType.CLICK,
            AgentActionType.DOWNLOAD,
        }
        if self.type == AgentActionType.FILL_FIELD:
            if not self.element_id or not self.document_field_ref:
                raise ValueError("FILL_FIELD requires element and document references.")
        elif self.type in element_actions:
            if not self.element_id or self.document_field_ref:
                raise ValueError(f"{self.type.value} requires only an element reference.")
        elif self.type == AgentActionType.OPEN_SEARCH_RESULT:
            if self.search_result_position is None:
                raise ValueError("OPEN_SEARCH_RESULT requires a result position.")
        elif self.type == AgentActionType.WAIT:
            if self.wait_seconds is None:
                raise ValueError("WAIT requires a bounded duration.")
        elif any(
            value is not None
            for value in (
                self.element_id,
                self.document_field_ref,
                self.search_result_position,
                self.wait_seconds,
            )
        ):
            raise ValueError("This action type does not accept execution references.")
        return self


class SafeActionRecord(StrictBrowserModel):
    step: int = Field(ge=1)
    action_type: AgentActionType
    element_id: str | None = None
    document_semantic_type: str | None = None
    target_domain: str | None = None
    outcome: str = Field(min_length=1)


class RetrievalChoice(StrictBrowserModel):
    label: str = Field(min_length=1)
    value: str = Field(min_length=1)


class RetrievalUserInputRequirement(StrictBrowserModel):
    required: bool
    reason: str | None = None
    requested_information: list[str]
    choices: list[RetrievalChoice] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_requirement(self) -> "RetrievalUserInputRequirement":
        if self.required and not self.reason:
            raise ValueError("Required retrieval input must include a reason.")
        if not self.required and (
            self.reason or self.requested_information or self.choices
        ):
            raise ValueError("Optional retrieval input cannot request information.")
        return self


class UserProvidedField(StrictBrowserModel):
    label: str = Field(min_length=1)
    value: str = Field(min_length=1)
    semantic_type: str = "unknown"


class DownloadedFile(StrictBrowserModel):
    path: str = Field(min_length=1)
    media_type: str = "application/pdf"
    size_bytes: int = Field(gt=0)
    validation_status: str = "validated"


class SafePageDiagnostics(StrictBrowserModel):
    page_type: PageType
    form_count: int = Field(ge=0)
    input_count: int = Field(ge=0)
    button_count: int = Field(ge=0)
    link_count: int = Field(ge=0)
    download_candidate_count: int = Field(ge=0)
    embedded_resource_count: int = Field(ge=0)
    dated_report_candidate_count: int = Field(ge=0)
    authentication_required: bool
    verification_required: bool
    relevant_message_count: int = Field(ge=0)
    document_media_type: str | None = None
    pending_download_detected: bool = False


class RetrievalResult(StrictBrowserModel):
    status: RetrievalStatus
    downloaded_file: DownloadedFile | None = None
    final_page_type: PageType | None = None
    current_domain: str | None = None
    steps_completed: int = Field(ge=0)
    user_input_requirement: RetrievalUserInputRequirement
    warnings: list[str]
    failure_reason: str | None = None
    safe_action_history: list[SafeActionRecord]
    field_mappings: list[FieldMatch]
    final_page_diagnostics: SafePageDiagnostics | None = None

    @model_validator(mode="after")
    def validate_retrieval_result(self) -> "RetrievalResult":
        if self.status == RetrievalStatus.DOWNLOADED and self.downloaded_file is None:
            raise ValueError("Downloaded retrieval results require a validated file.")
        if self.status != RetrievalStatus.DOWNLOADED and self.downloaded_file is not None:
            raise ValueError("Only downloaded retrieval results may include a file.")
        needs_input = self.status in {
            RetrievalStatus.USER_INPUT_REQUIRED,
            RetrievalStatus.AMBIGUOUS,
        }
        if self.user_input_requirement.required != needs_input:
            raise ValueError("Retrieval status and user-input requirement disagree.")
        return self
