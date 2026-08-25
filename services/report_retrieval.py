"""Reusable orchestration over the existing document, workflow, and browser engine."""

from pathlib import Path

from browser_agent.agent import RetrievalAgent
from browser_agent.models import RetrievalResult, RetrievalStatus, UserProvidedField
from config.settings import Settings
from document_understanding.models import AnalysisStatus, DocumentUnderstandingResult
from document_understanding.provider import create_document_provider
from document_understanding.service import DocumentUnderstandingService
from services.files import validate_report_path
from services.models import (
    ProgressCallback,
    ProgressEvent,
    ProgressStage,
    ReportRetrievalOutcome,
    RetrievalOutcomeStatus,
    RetrievedReport,
    SAFE_PROGRESS_MESSAGES,
)
from utils.logger import get_logger
from workflow.models import ActionType, PlanningStatus, WorkflowPlan
from workflow.planner import WorkflowPlanner


logger = get_logger(__name__)


class ReportRetrievalService:
    """UI-neutral application service that delegates to the existing engine."""

    def __init__(
        self,
        settings: Settings,
        document_service: DocumentUnderstandingService | None = None,
        planner: WorkflowPlanner | None = None,
        retrieval_agent: RetrievalAgent | None = None,
    ) -> None:
        self._settings = settings
        self._document_service = document_service
        self._planner = planner or WorkflowPlanner()
        self._retrieval_agent = retrieval_agent

    @classmethod
    def from_settings(cls, settings: Settings) -> "ReportRetrievalService":
        return cls(settings=settings)

    def analyze_document(self, image_path: Path) -> DocumentUnderstandingResult:
        if self._document_service is None:
            self._document_service = DocumentUnderstandingService(
                create_document_provider(self._settings)
            )
        return self._document_service.analyze(image_path)

    def plan_workflow(self, document: DocumentUnderstandingResult) -> WorkflowPlan:
        return self._planner.plan(document)

    def plan_user_provided_url(
        self, document: DocumentUnderstandingResult, value: str
    ) -> WorkflowPlan:
        return self._planner.plan_user_provided_url(document, value)

    def retrieve_prepared(
        self,
        document: DocumentUnderstandingResult,
        plan: WorkflowPlan,
        *,
        user_fields: list[UserProvidedField] | None = None,
        selected_choice: str | None = None,
    ) -> RetrievalResult:
        if self._retrieval_agent is None:
            self._retrieval_agent = RetrievalAgent.from_settings(self._settings)
        return self._retrieval_agent.run(
            document,
            plan,
            user_fields=user_fields,
            selected_choice=selected_choice,
        )

    def retrieve(
        self,
        image_path: Path,
        progress_callback: ProgressCallback | None = None,
    ) -> ReportRetrievalOutcome:
        """Run one complete retrieval and return only safe status and file references."""
        try:
            self._emit(ProgressStage.UPLOADED, progress_callback)
            self._emit(ProgressStage.READING_DOCUMENT, progress_callback)
            document = self.analyze_document(image_path)
            if document.analysis_status == AnalysisStatus.UNCLEAR:
                return self._failed("unreadable_document", progress_callback)

            self._emit(ProgressStage.DOCUMENT_UNDERSTOOD, progress_callback)
            self._emit(ProgressStage.PLANNING, progress_callback)
            plan = self.plan_workflow(document)
            if plan.status == PlanningStatus.USER_INPUT_REQUIRED:
                return self._terminal(
                    RetrievalOutcomeStatus.USER_INPUT_REQUIRED,
                    ProgressStage.USER_INPUT_REQUIRED,
                    progress_callback,
                )
            if plan.status == PlanningStatus.UNSUPPORTED:
                return self._failed("unsupported_document", progress_callback)
            if plan.status == PlanningStatus.FAILED:
                return self._failed("planning_failed", progress_callback)
            if plan.status not in {
                PlanningStatus.READY,
                PlanningStatus.SEARCH_REQUIRED,
            }:
                return self._failed("planning_failed", progress_callback)

            portal_stage = (
                ProgressStage.FINDING_PORTAL
                if plan.required_next_action.type == ActionType.SEARCH_WEB
                else ProgressStage.OPENING_PORTAL
            )
            self._emit(portal_stage, progress_callback)
            self._emit(ProgressStage.ENTERING_INFORMATION, progress_callback)
            self._emit(ProgressStage.RETRIEVING_REPORTS, progress_callback)
            retrieval = self.retrieve_prepared(document, plan)
            return self._map_retrieval(retrieval, progress_callback)
        except Exception as exc:  # Values and exception messages are never logged.
            logger.error("Application service retrieval failed: %s", type(exc).__name__)
            return self._failed("retrieval_failed", progress_callback)

    def _map_retrieval(
        self,
        retrieval: RetrievalResult,
        callback: ProgressCallback | None,
    ) -> ReportRetrievalOutcome:
        if retrieval.status == RetrievalStatus.DOWNLOADED:
            self._emit(ProgressStage.PREPARING_DOWNLOAD, callback)
            outcome = self._validated_outputs(retrieval)
            if outcome is None:
                return self._failed("invalid_report_output", callback)
            self._emit(ProgressStage.COMPLETED, callback)
            return outcome
        if retrieval.status in {
            RetrievalStatus.USER_INPUT_REQUIRED,
            RetrievalStatus.AMBIGUOUS,
        }:
            return self._terminal(
                RetrievalOutcomeStatus.USER_INPUT_REQUIRED,
                ProgressStage.USER_INPUT_REQUIRED,
                callback,
            )
        if retrieval.status == RetrievalStatus.VERIFICATION_REQUIRED:
            return self._terminal(
                RetrievalOutcomeStatus.VERIFICATION_REQUIRED,
                ProgressStage.VERIFICATION_REQUIRED,
                callback,
            )
        failure_type = {
            RetrievalStatus.REPORT_NOT_FOUND: "report_not_found",
            RetrievalStatus.UNSUPPORTED: "unsupported_retrieval",
            RetrievalStatus.FAILED: "retrieval_failed",
        }.get(retrieval.status, "retrieval_failed")
        return self._failed(failure_type, callback)

    def _validated_outputs(
        self, retrieval: RetrievalResult
    ) -> ReportRetrievalOutcome | None:
        downloaded = retrieval.downloaded_file
        if downloaded is None:
            return None

        reports: list[RetrievedReport] = []
        for index, item in enumerate(downloaded.individual_reports, 1):
            validated = validate_report_path(
                Path(item.path),
                allowed_directory=self._settings.temp_dir,
                max_download_mb=self._settings.max_report_download_mb,
                expected_content_type=item.media_type,
            )
            if validated is None or validated.content_type == "application/zip":
                return None
            reports.append(
                RetrievedReport(
                    path=validated.path,
                    display_name=item.display_name or f"Report {index}",
                    content_type=validated.content_type,
                    size_bytes=validated.size_bytes,
                )
            )

        primary = validate_report_path(
            Path(downloaded.path),
            allowed_directory=self._settings.temp_dir,
            max_download_mb=self._settings.max_report_download_mb,
            expected_content_type=downloaded.media_type,
        )
        if primary is None:
            return None

        bundle = None
        if primary.content_type == "application/zip":
            if not reports:
                return None
            bundle = RetrievedReport(
                path=primary.path,
                display_name="All reports",
                content_type=primary.content_type,
                size_bytes=primary.size_bytes,
            )
        elif not reports:
            reports.append(
                RetrievedReport(
                    path=primary.path,
                    display_name=downloaded.display_name or "Report 1",
                    content_type=primary.content_type,
                    size_bytes=primary.size_bytes,
                )
            )

        return ReportRetrievalOutcome(
            status=RetrievalOutcomeStatus.COMPLETED,
            reports=reports,
            bundle=bundle,
        )

    def _failed(
        self, failure_type: str, callback: ProgressCallback | None
    ) -> ReportRetrievalOutcome:
        self._emit(ProgressStage.FAILED, callback)
        return ReportRetrievalOutcome(
            status=RetrievalOutcomeStatus.FAILED,
            safe_failure_type=failure_type,
        )

    def _terminal(
        self,
        status: RetrievalOutcomeStatus,
        stage: ProgressStage,
        callback: ProgressCallback | None,
    ) -> ReportRetrievalOutcome:
        self._emit(stage, callback)
        return ReportRetrievalOutcome(status=status)

    @staticmethod
    def _emit(stage: ProgressStage, callback: ProgressCallback | None) -> None:
        if callback is not None:
            callback(ProgressEvent(stage=stage, message=SAFE_PROGRESS_MESSAGES[stage]))
