"""Request-bound retrieval routes for scale-to-zero container platforms."""

import secrets

import anyio
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse

from backend.dependencies import (
    get_backend_settings,
    get_report_retrieval_service,
    get_result_store,
)
from backend.jobs import JobRecord, JobStore
from backend.outcomes import public_files, store_outcome
from backend.schemas import JobStatus, RetrievalResultResponse
from backend.uploads import save_slip_upload
from config.settings import Settings
from services.models import SAFE_PROGRESS_MESSAGES, ProgressStage
from services.report_retrieval import ReportRetrievalService
from utils.file_utils import remove_files
from utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1", tags=["synchronous retrieval"])


@router.post("/retrieve", response_model=RetrievalResultResponse)
async def retrieve_report(
    request: Request,
    slip: UploadFile = File(...),
    settings: Settings = Depends(get_backend_settings),
    store: JobStore = Depends(get_result_store),
    service: ReportRetrievalService = Depends(get_report_retrieval_service),
) -> RetrievalResultResponse:
    if settings.backend_execution_mode != "synchronous":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Synchronous retrieval is not enabled.",
        )
    if not request.app.state.accepting_jobs:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The report service is shutting down.",
        )

    upload_path = await save_slip_upload(slip, settings)
    result_id = secrets.token_urlsafe(18)
    try:
        store.create(result_id, upload_path)
        outcome = await anyio.to_thread.run_sync(service.retrieve, upload_path)
        store_outcome(result_id, outcome, store)
    except Exception as exc:
        logger.error("Synchronous retrieval failed unexpectedly: %s", type(exc).__name__)
        record = store.get(result_id)
        if record is None:
            remove_files([upload_path], settings.temp_dir)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="The report request could not be completed.",
            ) from exc
        store.set_terminal(
            result_id,
            status=JobStatus.FAILED,
            stage=ProgressStage.FAILED,
            message=SAFE_PROGRESS_MESSAGES[ProgressStage.FAILED],
            safe_failure_type="retrieval_failed",
        )
    finally:
        store.discard_upload(result_id)

    record = store.get(result_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The report result is no longer available.",
        )
    return _result_response(record)


@router.get("/results/{result_id}", response_model=RetrievalResultResponse)
def get_result(
    result_id: str,
    store: JobStore = Depends(get_result_store),
) -> RetrievalResultResponse:
    record = store.get(result_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Result not found.")
    return _result_response(record)


@router.get("/results/{result_id}/files/{file_id}", response_class=FileResponse)
def download_result_file(
    result_id: str,
    file_id: str,
    store: JobStore = Depends(get_result_store),
) -> FileResponse:
    result_file = store.get_file(result_id, file_id)
    if result_file is None:
        raise HTTPException(status_code=404, detail="File not found.")
    return FileResponse(
        path=result_file.path,
        media_type=result_file.content_type,
        filename=result_file.download_name,
        headers={"Cache-Control": "private, no-store"},
    )


@router.delete("/results/{result_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_result(
    result_id: str,
    store: JobStore = Depends(get_result_store),
) -> None:
    if not store.delete(result_id):
        raise HTTPException(status_code=404, detail="Result not found.")


def _result_response(record: JobRecord) -> RetrievalResultResponse:
    reports, bundle = public_files(record)
    return RetrievalResultResponse(
        result_id=record.job_id,
        status=record.status,
        stage=record.stage,
        message=record.message,
        created_at=record.created_at,
        reports=reports,
        bundle_available=bundle is not None,
        bundle=bundle,
        failure_type=record.safe_failure_type,
    )
