"""FastAPI entry point for mobile and other non-Streamlit clients."""

from contextlib import asynccontextmanager

import anyio
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.dependencies import get_job_runner, get_job_store, get_result_store
from backend.jobs import JobRunner, JobStore
from backend.routes.reports import router as reports_router
from backend.routes.synchronous import router as synchronous_router
from backend.schemas import HealthResponse
from config.settings import Settings, get_settings
from utils.file_utils import cleanup_stale_files, ensure_temp_directory
from utils.logger import configure_logging, get_logger

logger = get_logger(__name__)


def validate_production_settings(settings: Settings) -> None:
    """Fail startup rather than silently weaken a production deployment."""
    if settings.backend_execution_mode not in {"background", "synchronous"}:
        raise RuntimeError(
            "BACKEND_EXECUTION_MODE must be 'background' or 'synchronous'."
        )
    if settings.app_env.casefold() != "production":
        return
    if settings.debug_mode:
        raise RuntimeError("DEBUG_MODE must be disabled in production.")
    if not settings.browser_headless:
        raise RuntimeError("BROWSER_HEADLESS must be enabled in production.")
    if settings.allow_insecure_report_portals:
        raise RuntimeError(
            "ALLOW_INSECURE_REPORT_PORTALS must be disabled in production."
        )
    provider = settings.document_ai_provider.casefold()
    if provider == "gemini" and not settings.gemini_api_key:
        raise RuntimeError("Gemini document analysis is not configured.")
    if provider == "openai" and not settings.document_ai_api_key:
        raise RuntimeError("OpenAI document analysis is not configured.")


def initialize_backend(settings: Settings) -> None:
    validate_production_settings(settings)
    configure_logging(settings.log_level)
    temp_dir = ensure_temp_directory(settings.temp_dir)
    cleanup_stale_files(temp_dir, settings.temp_file_max_age_hours)
    logger.info("Backend application started")


def shutdown_backend_resources(
    runner: JobRunner | None,
    store: JobStore | None,
    result_store: JobStore | None = None,
) -> None:
    """Drain the active job, cancel queued jobs, then remove unreachable files."""
    try:
        if runner is not None:
            runner.shutdown(wait=True)
    finally:
        try:
            if store is not None:
                store.cleanup_all()
        finally:
            if result_store is not None:
                result_store.cleanup_all()


def shutdown_cached_backend_resources() -> None:
    """Close only resources that were materialized by this application process."""
    runner = get_job_runner() if get_job_runner.cache_info().currsize else None
    store = get_job_store() if get_job_store.cache_info().currsize else None
    result_store = (
        get_result_store() if get_result_store.cache_info().currsize else None
    )
    try:
        shutdown_backend_resources(runner, store, result_store)
    finally:
        get_job_runner.cache_clear()
        get_job_store.cache_clear()
        get_result_store.cache_clear()
    logger.info("Backend application stopped")


@asynccontextmanager
async def backend_lifespan(api: FastAPI):
    initialize_backend(get_settings())
    api.state.accepting_jobs = True
    try:
        yield
    finally:
        api.state.accepting_jobs = False
        await anyio.to_thread.run_sync(shutdown_cached_backend_resources)


def create_app() -> FastAPI:
    settings = get_settings()
    api = FastAPI(
        title="Slip Automation API",
        version="1.0.0",
        docs_url="/docs" if settings.app_env == "development" else None,
        redoc_url=None,
        lifespan=backend_lifespan,
    )
    api.state.accepting_jobs = True

    @api.exception_handler(Exception)
    async def safe_unhandled_error(request: Request, exc: Exception) -> JSONResponse:
        del request
        logger.error("Unhandled API request failed: %s", type(exc).__name__)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "The request could not be completed."},
        )

    if settings.api_allowed_origins:
        api.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.api_allowed_origins),
            allow_credentials=True,
            allow_methods=["GET", "POST", "DELETE"],
            allow_headers=["Content-Type"],
        )

    @api.get("/health", response_model=HealthResponse, tags=["health"])
    def health() -> HealthResponse:
        return HealthResponse()

    api.include_router(reports_router)
    api.include_router(synchronous_router)
    return api


app = create_app()
