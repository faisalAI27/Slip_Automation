"""Map internal retrieval outcomes to ephemeral API artifact records."""

import secrets

from backend.jobs import JobRecord, JobStore
from backend.schemas import BundleFileResponse, JobStatus, ReportFileResponse
from services.models import (
    SAFE_PROGRESS_MESSAGES,
    ProgressStage,
    ReportRetrievalOutcome,
    RetrievalOutcomeStatus,
)


def store_outcome(
    record_id: str,
    outcome: ReportRetrievalOutcome,
    store: JobStore,
) -> bool:
    if outcome.status == RetrievalOutcomeStatus.COMPLETED:
        reports = [(secrets.token_urlsafe(12), item) for item in outcome.reports]
        bundle = (
            (secrets.token_urlsafe(12), outcome.bundle)
            if outcome.bundle is not None
            else None
        )
        return store.complete(record_id, reports, bundle)
    if outcome.status == RetrievalOutcomeStatus.USER_INPUT_REQUIRED:
        store.set_terminal(
            record_id,
            status=JobStatus.USER_INPUT_REQUIRED,
            stage=ProgressStage.USER_INPUT_REQUIRED,
            message=SAFE_PROGRESS_MESSAGES[ProgressStage.USER_INPUT_REQUIRED],
        )
        return store.get(record_id) is not None
    if outcome.status == RetrievalOutcomeStatus.VERIFICATION_REQUIRED:
        store.set_terminal(
            record_id,
            status=JobStatus.VERIFICATION_REQUIRED,
            stage=ProgressStage.VERIFICATION_REQUIRED,
            message=SAFE_PROGRESS_MESSAGES[ProgressStage.VERIFICATION_REQUIRED],
        )
        return store.get(record_id) is not None
    store.set_terminal(
        record_id,
        status=JobStatus.FAILED,
        stage=ProgressStage.FAILED,
        message=SAFE_PROGRESS_MESSAGES[ProgressStage.FAILED],
        safe_failure_type=outcome.safe_failure_type or "retrieval_failed",
    )
    return store.get(record_id) is not None


def public_files(
    record: JobRecord,
) -> tuple[list[ReportFileResponse], BundleFileResponse | None]:
    reports = [
        ReportFileResponse(
            file_id=file_id,
            display_name=record.files[file_id].display_name,
            content_type=record.files[file_id].content_type,
        )
        for file_id in record.report_file_ids
        if file_id in record.files
    ]
    bundle = None
    if record.bundle_file_id and record.bundle_file_id in record.files:
        bundle_file = record.files[record.bundle_file_id]
        bundle = BundleFileResponse(
            file_id=bundle_file.file_id,
            content_type=bundle_file.content_type,
        )
    return reports, bundle
