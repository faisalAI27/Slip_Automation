from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from browser_agent.models import (
    DownloadedFile,
    DownloadedReportFile,
    PageType,
    RetrievalResult,
    RetrievalStatus,
    RetrievalUserInputRequirement,
)
from config.settings import get_settings
from document_understanding.models import DocumentUnderstandingResult
from services.models import ProgressStage, RetrievalOutcomeStatus
from services.report_retrieval import ReportRetrievalService
from tests.test_result_view import RESULT_PAYLOAD
from workflow.planner import WorkflowPlanner


class FakeDocumentService:
    def __init__(self, result):
        self.result = result
        self.paths = []

    def analyze(self, image_path):
        self.paths.append(image_path)
        return self.result


class FakeRetrievalAgent:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def run(self, document, plan, *, user_fields=None, selected_choice=None):
        self.calls.append((document, plan, user_fields, selected_choice))
        return self.result


def _retrieval_result(downloaded_file):
    return RetrievalResult(
        status=RetrievalStatus.DOWNLOADED,
        downloaded_file=downloaded_file,
        final_page_type=PageType.REPORT_VIEWER,
        current_domain="example.test",
        steps_completed=4,
        user_input_requirement=RetrievalUserInputRequirement(
            required=False,
            reason=None,
            requested_information=[],
        ),
        warnings=[],
        failure_reason=None,
        safe_action_history=[],
        field_mappings=[],
    )


class ReportRetrievalServiceTests(unittest.TestCase):
    def test_complete_pipeline_uses_injected_engine_and_preserves_multiple_reports(
        self,
    ):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            image = root / "upload-test.png"
            report_one = root / "one.pdf"
            report_two = root / "two.pdf"
            bundle = root / "bundle.zip"
            image.write_bytes(b"synthetic input")
            report_one.write_bytes(b"%PDF-1.7\none")
            report_two.write_bytes(b"%PDF-1.7\ntwo")
            bundle.write_bytes(b"PK\x03\x04bundle")

            document = DocumentUnderstandingResult.model_validate(RESULT_PAYLOAD)
            document_service = FakeDocumentService(document)
            retrieval_agent = FakeRetrievalAgent(
                _retrieval_result(
                    DownloadedFile(
                        path=str(bundle),
                        media_type="application/zip",
                        size_bytes=bundle.stat().st_size,
                        report_count=2,
                        individual_reports=[
                            DownloadedReportFile(
                                path=str(report_one),
                                media_type="application/pdf",
                                size_bytes=report_one.stat().st_size,
                                display_name="ESR",
                            ),
                            DownloadedReportFile(
                                path=str(report_two),
                                media_type="application/pdf",
                                size_bytes=report_two.stat().st_size,
                                display_name="Albumin",
                            ),
                        ],
                    )
                )
            )
            service = ReportRetrievalService(
                settings=replace(get_settings(), temp_dir=root),
                document_service=document_service,
                planner=WorkflowPlanner(),
                retrieval_agent=retrieval_agent,
            )
            events = []

            outcome = service.retrieve(image, events.append)

            self.assertEqual(outcome.status, RetrievalOutcomeStatus.COMPLETED)
            self.assertEqual(
                [item.display_name for item in outcome.reports], ["ESR", "Albumin"]
            )
            self.assertIsNotNone(outcome.bundle)
            self.assertEqual(len(document_service.paths), 1)
            self.assertEqual(len(retrieval_agent.calls), 1)
            self.assertEqual(events[-1].stage, ProgressStage.COMPLETED)
            serialized_events = " ".join(item.model_dump_json() for item in events)
            self.assertNotIn("PATIENT-123", serialized_events.upper())
            self.assertNotIn("ACCESS-CODE-SECRET", serialized_events.upper())

    def test_output_outside_owned_temp_directory_is_rejected(self):
        with TemporaryDirectory() as allowed, TemporaryDirectory() as elsewhere:
            allowed_root = Path(allowed)
            external = Path(elsewhere) / "report.pdf"
            external.write_bytes(b"%PDF-1.7\nexternal")
            document = DocumentUnderstandingResult.model_validate(RESULT_PAYLOAD)
            service = ReportRetrievalService(
                settings=replace(get_settings(), temp_dir=allowed_root),
                document_service=FakeDocumentService(document),
                planner=WorkflowPlanner(),
                retrieval_agent=FakeRetrievalAgent(
                    _retrieval_result(
                        DownloadedFile(
                            path=str(external),
                            media_type="application/pdf",
                            size_bytes=external.stat().st_size,
                        )
                    )
                ),
            )

            outcome = service.retrieve(allowed_root / "upload.png")

            self.assertEqual(outcome.status, RetrievalOutcomeStatus.FAILED)
            self.assertEqual(outcome.safe_failure_type, "invalid_report_output")


if __name__ == "__main__":
    unittest.main()
