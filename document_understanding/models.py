"""Validated domain models for general document understanding."""

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ConfidenceLevel(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"


class AnalysisStatus(str, Enum):
    USABLE = "usable"
    UNCLEAR = "unclear"
    NOT_MEDICAL = "not_medical"
    UNKNOWN = "unknown"


class OrganizationType(str, Enum):
    LABORATORY = "laboratory"
    HOSPITAL = "hospital"
    CLINIC = "clinic"
    DIAGNOSTIC_CENTER = "diagnostic_center"
    MEDICAL_CENTER = "medical_center"
    UNKNOWN = "unknown"


class FieldSemanticType(str, Enum):
    PATIENT_IDENTIFIER = "patient_identifier"
    REGISTRATION_IDENTIFIER = "registration_identifier"
    VISIT_IDENTIFIER = "visit_identifier"
    REFERENCE_IDENTIFIER = "reference_identifier"
    SAMPLE_IDENTIFIER = "sample_identifier"
    REPORT_IDENTIFIER = "report_identifier"
    ACCESS_CREDENTIAL = "access_credential"
    PHONE_NUMBER = "phone_number"
    EMAIL = "email"
    DATE = "date"
    PERSON_NAME = "person_name"
    ORGANIZATION_IDENTIFIER = "organization_identifier"
    UNKNOWN = "unknown"


class URLPurpose(str, Enum):
    REPORT_PORTAL = "report_portal"
    ORGANIZATION_HOMEPAGE = "organization_homepage"
    SUPPORT_PAGE = "support_page"
    PAYMENT_PAGE = "payment_page"
    UNKNOWN = "unknown"


class QRContentType(str, Enum):
    URL = "url"
    TEXT = "text"
    UNKNOWN = "unknown"


class DateSemanticType(str, Enum):
    REGISTRATION_DATE = "registration_date"
    COLLECTION_DATE = "collection_date"
    REPORT_DATE = "report_date"
    APPOINTMENT_DATE = "appointment_date"
    EXPIRY_DATE = "expiry_date"
    UNKNOWN = "unknown"


class OrganizationInfo(StrictModel):
    name: str | None = Field(description="Exact visible organization name, or null.")
    type: OrganizationType
    confidence: ConfidenceLevel


class ExtractedField(StrictModel):
    label: str | None = Field(description="Exact visible field label, or null if absent.")
    value: str = Field(description="Exact visible value without semantic rewriting.")
    semantic_type: FieldSemanticType
    confidence: ConfidenceLevel


class ExtractedURL(StrictModel):
    url: str = Field(description="URL exactly as printed in the document.")
    normalized_url: str | None = Field(
        description="Absolute http(s) URL when unambiguous, otherwise null."
    )
    context: str | None = Field(description="Short non-sensitive visual context.")
    likely_purpose: URLPurpose
    confidence: ConfidenceLevel


class QRCodeResult(StrictModel):
    value: str
    type: QRContentType
    confidence: ConfidenceLevel
    symbol_format: str | None = Field(
        description="Decoder-reported barcode format when independently decoded."
    )


class ExtractedDate(StrictModel):
    label: str | None = Field(description="Exact date label, or null if absent.")
    value: str = Field(description="Date exactly as printed.")
    semantic_type: DateSemanticType
    confidence: ConfidenceLevel


class DocumentUnderstandingResult(StrictModel):
    analysis_status: AnalysisStatus
    document_type: str = Field(
        description="Concise general document classification or 'unknown'."
    )
    document_type_confidence: ConfidenceLevel
    organization: OrganizationInfo | None
    purpose: str = Field(description="Likely document purpose or 'unknown'.")
    likely_action: str = Field(description="Likely expected user action or 'unknown'.")
    urls: list[ExtractedURL]
    qr_codes: list[QRCodeResult]
    fields: list[ExtractedField]
    dates: list[ExtractedDate]
    instructions: list[str]
    raw_summary: str = Field(description="Short internal summary without speculation.")
    overall_confidence: ConfidenceLevel
    warnings: list[str]
