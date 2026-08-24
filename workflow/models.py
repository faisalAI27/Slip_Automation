"""Strict, UI-independent models for Phase 3 workflow planning."""

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from document_understanding.models import (
    ConfidenceLevel,
    DateSemanticType,
    FieldSemanticType,
    OrganizationType,
    URLPurpose,
)


class StrictPlanningModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class PlanningStatus(str, Enum):
    READY = "ready"
    SEARCH_REQUIRED = "search_required"
    USER_INPUT_REQUIRED = "user_input_required"
    UNSUPPORTED = "unsupported"
    FAILED = "failed"


class ActionType(str, Enum):
    OPEN_URL = "open_url"
    SEARCH_WEB = "search_web"
    INSPECT_PAGE = "inspect_page"
    REQUEST_USER_INPUT = "request_user_input"
    STOP = "stop"


class PortalSource(str, Enum):
    PRINTED_URL = "printed_url"
    QR_CODE = "qr_code"
    ORGANIZATION_HOMEPAGE = "organization_homepage"
    USER_PROVIDED_URL = "user_provided_url"
    FUTURE_WEB_SEARCH = "future_web_search"


class PortalStrategy(str, Enum):
    EXPLICIT_REPORT_URL = "explicit_report_url"
    QR_REPORT_URL = "qr_report_url"
    ORGANIZATION_HOMEPAGE = "organization_homepage"
    USER_PROVIDED_URL = "user_provided_url"
    WEB_SEARCH = "web_search"
    USER_INPUT_REQUIRED = "user_input_required"
    UNSUPPORTED = "unsupported"
    FAILED = "failed"


class InformationSource(str, Enum):
    DOCUMENT_FIELD = "document_field"
    DOCUMENT_DATE = "document_date"


class PotentialUse(str, Enum):
    PORTAL_FORM_INPUT = "portal_form_input"
    PORTAL_AUTHENTICATION = "portal_authentication"
    CONTACT_INFORMATION = "contact_information"
    REFERENCE_INFORMATION = "reference_information"
    CONTEXT_ONLY = "context_only"


class PlannedOrganization(StrictPlanningModel):
    name: str = Field(min_length=1)
    type: OrganizationType
    confidence: ConfidenceLevel


class PortalCandidate(StrictPlanningModel):
    url: str = Field(min_length=1)
    source: PortalSource
    likely_purpose: URLPurpose
    confidence: ConfidenceLevel
    reason: str = Field(min_length=1)


class AvailableField(StrictPlanningModel):
    label: str | None
    value: str = Field(min_length=1)
    semantic_type: FieldSemanticType | DateSemanticType
    source: InformationSource
    potential_use: PotentialUse
    confidence: ConfidenceLevel


class NextAction(StrictPlanningModel):
    type: ActionType
    target: str | None = None
    query: str | None = None
    reason: str = Field(min_length=1)
    confidence: ConfidenceLevel

    @model_validator(mode="after")
    def validate_action_payload(self) -> "NextAction":
        if self.type == ActionType.OPEN_URL:
            if not self.target or self.query:
                raise ValueError("OPEN_URL requires only a target URL.")
        elif self.type == ActionType.SEARCH_WEB:
            if not self.query or self.target:
                raise ValueError("SEARCH_WEB requires only a search query.")
        elif self.type == ActionType.STOP and (self.target or self.query):
            raise ValueError("STOP cannot contain a target or query.")
        return self


class UserInputRequirement(StrictPlanningModel):
    required: bool
    reason: str | None = None
    requested_information: list[str]

    @model_validator(mode="after")
    def validate_requirement(self) -> "UserInputRequirement":
        if self.required and not self.reason:
            raise ValueError("Required user input must include a reason.")
        if not self.required and (self.reason or self.requested_information):
            raise ValueError("Optional user input cannot request information.")
        return self


class WorkflowPlan(StrictPlanningModel):
    goal: str = Field(min_length=1)
    status: PlanningStatus
    organization: PlannedOrganization | None
    portal_strategy: PortalStrategy
    portal_candidates: list[PortalCandidate]
    available_fields: list[AvailableField]
    required_next_action: NextAction
    user_input_requirement: UserInputRequirement
    warnings: list[str]
    planner_summary: str = Field(min_length=1)
