"""Job-based report retrieval API routes."""

from pathlib import Path
import secrets

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse

from backend.dependencies import (
    get_backend_settings,
    get_job_runner,
    get_job_store,
    get_report_retrieval_service,
)
from backend.jobs import JobRecord, JobRunner, JobStore
from backend.schemas import (
    BundleFileResponse,
    JobCreatedResponse,
    JobStatus,
    JobStatusResponse,
    ReportFileResponse,
)
from config.settings import Settings
from services.models import (
    ProgressStage,
    ReportRetrievalOutcome,
    RetrievalOutcomeStatus,
    SAFE_PROGRESS_MESSAGES,
)
from services.report_retrieval import ReportRetrievalService
from utils.file_utils import (
    ImageTooLargeError,
    InvalidImageError,
    UnsupportedImageError,
    remove_files,
    save_uploaded_image,
)
from utils.logger import get_logger


logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/jobs", tags=["report jobs"])


@router.post(
    "",
    response_model=JobCreatedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_job(
    slip: UploadFile = File(...),
    settings: Settings = Depends(get_backend_settings),
    store: JobStore = Depends(get_job_store),
    runner: JobRunner = Depends(get_job_runner),
    service: ReportRetrievalService = Depends(get_report_retrieval_service),
) -> JobCreatedResponse:
    maximum_bytes = settings.max_upload_mb * 1024 * 1024
    file_data = await slip.read(maximum_bytes + 1)
    if len(file_data) > maximum_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="The uploaded image exceeds the configured size limit.",
        )

    try:
        upload_path = save_uploaded_image(
            file_data=file_data,
            original_name=slip.filename or "upload",
            temp_dir=settings.temp_dir,
            max_upload_mb=settings.max_upload_mb,
        )
    except UnsupportedImageError as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Upload a JPG, JPEG, or PNG image.",
        ) from exc
    except ImageTooLargeError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="The uploaded image exceeds the configured size limit.",
        ) from exc
    except InvalidImageError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The uploaded image could not be read.",
        ) from exc

    job_id = secrets.token_urlsafe(18)
    try:
        store.create(job_id, upload_path)
        runner.submit(
            job_id,
            lambda: _run_job(job_id, upload_path, store, service),
        )
    except Exception as exc:
        remove_files([upload_path], settings.temp_dir)
        logger.error("Report job could not be queued: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The report job could not be queued.",
        ) from exc

    return JobCreatedResponse(job_id=job_id, status=JobStatus.QUEUED)


@router.get("/{job_id}", response_model=JobStatusResponse)
def get_job_status(
    job_id: str,
    store: JobStore = Depends(get_job_store),
) -> JobStatusResponse:
    record = store.get(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return _status_response(record)


@router.get("/{job_id}/files/{file_id}", response_class=FileResponse)
def download_job_file(
    job_id: str,
    file_id: str,
    store: JobStore = Depends(get_job_store),
) -> FileResponse:
    job_file = store.get_file(job_id, file_id)
    if job_file is None:
        raise HTTPException(status_code=404, detail="File not found.")
    return FileResponse(
        path=job_file.path,
        media_type=job_file.content_type,
        filename=job_file.download_name,
        headers={"Cache-Control": "private, no-store"},
    )


def _run_job(
    job_id: str,
    upload_path: Path,
    store: JobStore,
    service: ReportRetrievalService,
) -> None:
    try:
        outcome = service.retrieve(
            upload_path,
            progress_callback=lambda event: store.update_progress(job_id, event),
        )
        stored = _store_outcome(job_id, outcome, store)
        if not stored and outcome.status == RetrievalOutcomeStatus.COMPLETED:
            remove_files(
                [
                    *(item.path for item in outcome.reports),
                    outcome.bundle.path if outcome.bundle else None,
                ],
                upload_path.parent,
            )
    except Exception as exc:  # No exception message or medical value is logged.
        logger.error("Report job failed unexpectedly: %s", type(exc).__name__)
        store.set_terminal(
            job_id,
            status=JobStatus.FAILED,
            stage=ProgressStage.FAILED,
            message=SAFE_PROGRESS_MESSAGES[ProgressStage.FAILED],
            safe_failure_type="retrieval_failed",
        )


def _store_outcome(
    job_id: str, outcome: ReportRetrievalOutcome, store: JobStore
) -> bool:
    if outcome.status == RetrievalOutcomeStatus.COMPLETED:
        reports = [(secrets.token_urlsafe(12), item) for item in outcome.reports]
        bundle = (
            (secrets.token_urlsafe(12), outcome.bundle)
            if outcome.bundle is not None
            else None
        )
        return store.complete(job_id, reports, bundle)
    if outcome.status == RetrievalOutcomeStatus.USER_INPUT_REQUIRED:
        store.set_terminal(
            job_id,
            status=JobStatus.USER_INPUT_REQUIRED,
            stage=ProgressStage.USER_INPUT_REQUIRED,
            message=SAFE_PROGRESS_MESSAGES[ProgressStage.USER_INPUT_REQUIRED],
        )
        return store.get(job_id) is not None
    if outcome.status == RetrievalOutcomeStatus.VERIFICATION_REQUIRED:
        store.set_terminal(
            job_id,
            status=JobStatus.VERIFICATION_REQUIRED,
            stage=ProgressStage.VERIFICATION_REQUIRED,
            message=SAFE_PROGRESS_MESSAGES[ProgressStage.VERIFICATION_REQUIRED],
        )
        return store.get(job_id) is not None
    store.set_terminal(
        job_id,
        status=JobStatus.FAILED,
        stage=ProgressStage.FAILED,
        message=SAFE_PROGRESS_MESSAGES[ProgressStage.FAILED],
        safe_failure_type=outcome.safe_failure_type or "retrieval_failed",
    )
    return store.get(job_id) is not None


def _status_response(record: JobRecord) -> JobStatusResponse:
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
    return JobStatusResponse(
        job_id=record.job_id,
        status=record.status,
        stage=record.stage,
        message=record.message,
        created_at=record.created_at,
        reports=reports,
        bundle_available=bundle is not None,
        bundle=bundle,
        failure_type=record.safe_failure_type,
    )
