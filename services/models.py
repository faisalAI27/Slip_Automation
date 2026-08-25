"""Safe, provider- and UI-independent application service models."""

from collections.abc import Callable
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class StrictServiceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ProgressStage(str, Enum):
    UPLOADED = "uploaded"
    READING_DOCUMENT = "reading_document"
    DOCUMENT_UNDERSTOOD = "document_understood"
    PLANNING = "planning"
    FINDING_PORTAL = "finding_portal"
    OPENING_PORTAL = "opening_portal"
    ENTERING_INFORMATION = "entering_information"
    RETRIEVING_REPORTS = "retrieving_reports"
    PREPARING_DOWNLOAD = "preparing_download"
    COMPLETED = "completed"
    FAILED = "failed"
    USER_INPUT_REQUIRED = "user_input_required"
    VERIFICATION_REQUIRED = "verification_required"


SAFE_PROGRESS_MESSAGES: dict[ProgressStage, str] = {
    ProgressStage.UPLOADED: "Slip uploaded",
    ProgressStage.READING_DOCUMENT: "Reading your slip",
    ProgressStage.DOCUMENT_UNDERSTOOD: "Slip understood",
    ProgressStage.PLANNING: "Preparing a safe retrieval plan",
    ProgressStage.FINDING_PORTAL: "Finding the official report service",
    ProgressStage.OPENING_PORTAL: "Opening the report service",
    ProgressStage.ENTERING_INFORMATION: "Entering report access information",
    ProgressStage.RETRIEVING_REPORTS: "Retrieving your report",
    ProgressStage.PREPARING_DOWNLOAD: "Preparing your download",
    ProgressStage.COMPLETED: "Report ready",
    ProgressStage.FAILED: "Report retrieval stopped",
    ProgressStage.USER_INPUT_REQUIRED: "More information is required",
    ProgressStage.VERIFICATION_REQUIRED: "Website verification is required",
}


class ProgressEvent(StrictServiceModel):
    stage: ProgressStage
    message: str = Field(min_length=1, max_length=160)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


ProgressCallback = Callable[[ProgressEvent], None]


class RetrievalOutcomeStatus(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    USER_INPUT_REQUIRED = "user_input_required"
    VERIFICATION_REQUIRED = "verification_required"


class SafeFailureType(str, Enum):
    UNREADABLE_DOCUMENT = "unreadable_document"
    UNSUPPORTED_DOCUMENT = "unsupported_document"
    PLANNING_FAILED = "planning_failed"
    RETRIEVAL_FAILED = "retrieval_failed"
    INVALID_REPORT_OUTPUT = "invalid_report_output"
    REPORT_NOT_FOUND = "report_not_found"
    UNSUPPORTED_RETRIEVAL = "unsupported_retrieval"


class RetrievedReport(StrictServiceModel):
    """Internal validated output reference; paths never enter API schemas."""

    path: Path
    display_name: str = Field(min_length=1, max_length=120)
    content_type: str
    size_bytes: int = Field(gt=0)


class ReportRetrievalOutcome(StrictServiceModel):
    status: RetrievalOutcomeStatus
    reports: list[RetrievedReport] = Field(default_factory=list)
    bundle: RetrievedReport | None = None
    safe_failure_type: SafeFailureType | None = None
