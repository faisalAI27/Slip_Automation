"""FastAPI dependency providers for replaceable service infrastructure."""

from functools import lru_cache

from backend.jobs import JobRunner, JobStore, LocalJobRunner, LocalJobStore
from config.settings import Settings, get_settings
from services.report_retrieval import ReportRetrievalService


def get_backend_settings() -> Settings:
    return get_settings()


@lru_cache(maxsize=1)
def get_job_store() -> JobStore:
    settings = get_settings()
    return LocalJobStore(
        temp_dir=settings.temp_dir,
        ttl_minutes=settings.job_ttl_minutes,
    )


@lru_cache(maxsize=1)
def get_result_store() -> JobStore:
    """Separate ephemeral mapping for request-bound synchronous retrievals."""
    settings = get_settings()
    return LocalJobStore(
        temp_dir=settings.temp_dir,
        ttl_minutes=settings.job_ttl_minutes,
    )


@lru_cache(maxsize=1)
def get_job_runner() -> JobRunner:
    return LocalJobRunner(get_settings().backend_max_concurrent_jobs)


def get_report_retrieval_service() -> ReportRetrievalService:
    return ReportRetrievalService.from_settings(get_settings())
