"""Public API schemas; no domain object with credentials is serialized here."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from services.models import ProgressStage


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class JobStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    USER_INPUT_REQUIRED = "user_input_required"
    VERIFICATION_REQUIRED = "verification_required"


class HealthResponse(ApiModel):
    status: str = "ok"


class JobCreatedResponse(ApiModel):
    job_id: str
    status: JobStatus


class ReportFileResponse(ApiModel):
    file_id: str
    display_name: str
    content_type: str


class BundleFileResponse(ApiModel):
    file_id: str
    content_type: str


class JobStatusResponse(ApiModel):
    job_id: str
    status: JobStatus
    stage: ProgressStage
    message: str = Field(min_length=1, max_length=160)
    created_at: datetime
    reports: list[ReportFileResponse] = Field(default_factory=list)
    bundle_available: bool = False
    bundle: BundleFileResponse | None = None
    failure_type: str | None = None


class RetrievalResultResponse(ApiModel):
    result_id: str
    status: JobStatus
    stage: ProgressStage
    message: str = Field(min_length=1, max_length=160)
    created_at: datetime
    reports: list[ReportFileResponse] = Field(default_factory=list)
    bundle_available: bool = False
    bundle: BundleFileResponse | None = None
    failure_type: str | None = None
