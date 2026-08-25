"""Prototype local job storage and bounded background execution."""

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
from typing import Protocol

from backend.schemas import JobStatus
from services.models import (
    SAFE_PROGRESS_MESSAGES,
    ProgressEvent,
    ProgressStage,
    RetrievedReport,
)
from utils.file_utils import remove_files

Clock = Callable[[], datetime]


@dataclass(frozen=True, slots=True)
class JobFile:
    file_id: str
    path: Path
    display_name: str
    download_name: str
    content_type: str
    size_bytes: int


@dataclass(slots=True)
class JobRecord:
    job_id: str
    status: JobStatus
    stage: ProgressStage
    message: str
    created_at: datetime
    expires_at: datetime
    upload_path: Path | None
    files: dict[str, JobFile] = field(default_factory=dict)
    report_file_ids: list[str] = field(default_factory=list)
    bundle_file_id: str | None = None
    safe_failure_type: str | None = None


class JobStore(Protocol):
    """Replaceable store contract for a future durable deployment backend."""

    def create(self, job_id: str, upload_path: Path) -> JobRecord: ...

    def get(self, job_id: str) -> JobRecord | None: ...

    def update_progress(self, job_id: str, event: ProgressEvent) -> None: ...

    def complete(
        self,
        job_id: str,
        reports: list[tuple[str, RetrievedReport]],
        bundle: tuple[str, RetrievedReport] | None,
    ) -> bool: ...

    def set_terminal(
        self,
        job_id: str,
        *,
        status: JobStatus,
        stage: ProgressStage,
        message: str,
        safe_failure_type: str | None = None,
    ) -> None: ...

    def get_file(self, job_id: str, file_id: str) -> JobFile | None: ...

    def cleanup_expired(self) -> int: ...

    def cleanup_all(self) -> int: ...


class LocalJobStore:
    """Thread-safe in-memory prototype store; state is lost on process restart."""

    def __init__(
        self,
        *,
        temp_dir: Path,
        ttl_minutes: int = 30,
        clock: Clock | None = None,
    ) -> None:
        self._temp_dir = temp_dir.resolve()
        self._ttl = timedelta(minutes=max(1, ttl_minutes))
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._jobs: dict[str, JobRecord] = {}
        self._lock = RLock()

    def create(self, job_id: str, upload_path: Path) -> JobRecord:
        now = self._clock()
        record = JobRecord(
            job_id=job_id,
            status=JobStatus.QUEUED,
            stage=ProgressStage.UPLOADED,
            message="Slip uploaded",
            created_at=now,
            expires_at=now + self._ttl,
            upload_path=upload_path.resolve(),
        )
        with self._lock:
            self._cleanup_expired_locked(now)
            if job_id in self._jobs:
                raise ValueError("Job identifier already exists.")
            self._jobs[job_id] = record
            return deepcopy(record)

    def get(self, job_id: str) -> JobRecord | None:
        with self._lock:
            self._cleanup_expired_locked(self._clock())
            record = self._jobs.get(job_id)
            return deepcopy(record) if record is not None else None

    def update_progress(self, job_id: str, event: ProgressEvent) -> None:
        with self._lock:
            self._cleanup_expired_locked(self._clock())
            record = self._jobs.get(job_id)
            if record is None or record.status in {
                JobStatus.COMPLETED,
                JobStatus.FAILED,
                JobStatus.USER_INPUT_REQUIRED,
                JobStatus.VERIFICATION_REQUIRED,
            }:
                return
            record.status = JobStatus.PROCESSING
            record.stage = event.stage
            record.message = SAFE_PROGRESS_MESSAGES[event.stage]

    def complete(
        self,
        job_id: str,
        reports: list[tuple[str, RetrievedReport]],
        bundle: tuple[str, RetrievedReport] | None,
    ) -> bool:
        with self._lock:
            self._cleanup_expired_locked(self._clock())
            record = self._jobs.get(job_id)
            if record is None:
                return False
            files: dict[str, JobFile] = {}
            report_ids: list[str] = []
            for index, (file_id, report) in enumerate(reports, 1):
                job_file = self._job_file(
                    file_id,
                    report,
                    f"report_{index}",
                    public_display_name=f"Report {index}",
                )
                files[file_id] = job_file
                report_ids.append(file_id)
            bundle_id = None
            if bundle is not None:
                bundle_id, report = bundle
                files[bundle_id] = self._job_file(
                    bundle_id,
                    report,
                    "reports_bundle",
                    public_display_name="All reports",
                )
            record.files = files
            record.report_file_ids = report_ids
            record.bundle_file_id = bundle_id
            record.status = JobStatus.COMPLETED
            record.stage = ProgressStage.COMPLETED
            record.message = "Report ready"
            record.safe_failure_type = None
            return True

    def set_terminal(
        self,
        job_id: str,
        *,
        status: JobStatus,
        stage: ProgressStage,
        message: str,
        safe_failure_type: str | None = None,
    ) -> None:
        if status not in {
            JobStatus.FAILED,
            JobStatus.USER_INPUT_REQUIRED,
            JobStatus.VERIFICATION_REQUIRED,
        }:
            raise ValueError("Terminal status is not supported.")
        with self._lock:
            self._cleanup_expired_locked(self._clock())
            record = self._jobs.get(job_id)
            if record is None:
                return
            record.status = status
            record.stage = stage
            record.message = SAFE_PROGRESS_MESSAGES[stage]
            record.safe_failure_type = safe_failure_type

    def get_file(self, job_id: str, file_id: str) -> JobFile | None:
        with self._lock:
            self._cleanup_expired_locked(self._clock())
            record = self._jobs.get(job_id)
            if record is None or record.status != JobStatus.COMPLETED:
                return None
            job_file = record.files.get(file_id)
            if job_file is None:
                return None
            resolved = job_file.path.resolve()
            if resolved.parent != self._temp_dir or not resolved.is_file():
                return None
            return deepcopy(job_file)

    def cleanup_expired(self) -> int:
        with self._lock:
            return self._cleanup_expired_locked(self._clock())

    def cleanup_all(self) -> int:
        """Remove every job and owned file when this process is shutting down."""
        with self._lock:
            records = list(self._jobs.values())
            self._jobs.clear()
            self._remove_record_files(records)
            return len(records)

    def _cleanup_expired_locked(self, now: datetime) -> int:
        expired_ids = [
            job_id for job_id, record in self._jobs.items() if record.expires_at <= now
        ]
        for job_id in expired_ids:
            self._remove_record_files([self._jobs.pop(job_id)])
        return len(expired_ids)

    def _remove_record_files(self, records: list[JobRecord]) -> None:
        paths = [
            path
            for record in records
            for path in [
                record.upload_path,
                *(item.path for item in record.files.values()),
            ]
        ]
        remove_files(list(dict.fromkeys(paths)), self._temp_dir)

    @staticmethod
    def _job_file(
        file_id: str,
        report: RetrievedReport,
        stem: str,
        *,
        public_display_name: str,
    ) -> JobFile:
        extension = {
            "application/pdf": ".pdf",
            "image/png": ".png",
            "image/jpeg": ".jpg",
            "application/zip": ".zip",
        }[report.content_type]
        return JobFile(
            file_id=file_id,
            path=report.path.resolve(),
            display_name=public_display_name,
            download_name=f"{stem}{extension}",
            content_type=report.content_type,
            size_bytes=report.size_bytes,
        )


class JobRunner(Protocol):
    def submit(self, job_id: str, task: Callable[[], None]) -> Future[None]: ...

    def shutdown(self, *, wait: bool = True) -> None: ...


class LocalJobRunner:
    """Bounded local runner; each worker may own one Chromium session."""

    def __init__(self, max_concurrent_jobs: int = 1) -> None:
        self.max_concurrent_jobs = max(1, max_concurrent_jobs)
        self._executor = ThreadPoolExecutor(
            max_workers=self.max_concurrent_jobs,
            thread_name_prefix="report-job",
        )

    def submit(self, job_id: str, task: Callable[[], None]) -> Future[None]:
        del job_id  # Reserved for a future external queue implementation.
        return self._executor.submit(task)

    def shutdown(self, *, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait, cancel_futures=True)
