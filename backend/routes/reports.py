"""Job-based report retrieval API routes."""

import secrets
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse

from backend.dependencies import (
    get_backend_settings,
    get_job_runner,
    get_job_store,
    get_report_retrieval_service,
)
from backend.jobs import JobRecord, JobRunner, JobStore
from backend.outcomes import public_files, store_outcome
from backend.schemas import (
    JobCreatedResponse,
    JobStatus,
    JobStatusResponse,
)
from backend.uploads import save_slip_upload
from config.settings import Settings
from services.models import SAFE_PROGRESS_MESSAGES, ProgressStage, RetrievalOutcomeStatus
from services.report_retrieval import ReportRetrievalService
from utils.file_utils import remove_files
from utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/jobs", tags=["report jobs"])


@router.post(
    "",
    response_model=JobCreatedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_job(
    request: Request,
    slip: UploadFile = File(...),
    settings: Settings = Depends(get_backend_settings),
    store: JobStore = Depends(get_job_store),
    runner: JobRunner = Depends(get_job_runner),
    service: ReportRetrievalService = Depends(get_report_retrieval_service),
) -> JobCreatedResponse:
    if settings.backend_execution_mode == "synchronous":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Background job execution is disabled.",
        )
    if not request.app.state.accepting_jobs:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The report service is shutting down.",
        )
    upload_path = await save_slip_upload(slip, settings)

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
        stored = store_outcome(job_id, outcome, store)
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
    finally:
        store.discard_upload(job_id)


def _status_response(record: JobRecord) -> JobStatusResponse:
    reports, bundle = public_files(record)
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
