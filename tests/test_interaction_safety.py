import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from browser_agent.download_manager import ReportDownloadManager
from browser_agent.errors import InteractionSafetyError
from browser_agent.field_matcher import DocumentFieldStore
from browser_agent.interaction import ControlledBrowserTools, InteractionSafetyValidator
from browser_agent.models import (
    AgentAction,
    AgentActionType,
    AuthenticationSignals,
    BrowserObservation,
    DownloadCandidateKind,
    FormObservation,
    HtmlInputType,
    InputFieldObservation,
    PageType,
    VerificationSignals,
)
from browser_agent.safety import ValidatedURL
from document_understanding.models import ConfidenceLevel, FieldSemanticType
from workflow.models import AvailableField, InformationSource, PotentialUse


def _store() -> DocumentFieldStore:
    return DocumentFieldStore(
        [
            AvailableField(
                label="MR Number",
                value="PRIVATE-VALUE",
                semantic_type=FieldSemanticType.PATIENT_IDENTIFIER,
                source=InformationSource.DOCUMENT_FIELD,
                potential_use=PotentialUse.PORTAL_AUTHENTICATION,
                confidence=ConfidenceLevel.HIGH,
            )
        ]
    )


def _observation(*, form_domain: str | None = None) -> BrowserObservation:
    return BrowserObservation(
        final_url="https://reports.example.test/login",
        final_domain="example.test",
        page_title="Login",
        page_type=PageType.REPORT_LOGIN_PAGE,
        visible_text_summary="Login",
        forms=[
            FormObservation(
                element_id="form_1",
                name="login",
                method="post",
                action_domain=form_domain,
                input_references=["input_1"],
            )
        ],
        input_fields=[
            InputFieldObservation(
                element_id="input_1",
                html_type=HtmlInputType.TEXT,
                name="patient",
                label="Patient Number",
                placeholder=None,
                aria_label=None,
                required=True,
                disabled=False,
                readonly=False,
                autocomplete=None,
            )
        ],
        buttons=[],
        links=[],
        download_candidates=[],
        authentication_signals=AuthenticationSignals(
            authentication_required=True,
            field_count=1,
            confidence=ConfidenceLevel.HIGH,
        ),
        verification_signals=VerificationSignals(
            otp_detected=False,
            captcha_detected=False,
            email_verification_detected=False,
            verification_required=False,
        ),
        errors_or_messages=[],
        warnings=[],
    )


def _fill(ref: str = "input_1") -> AgentAction:
    return AgentAction(
        type=AgentActionType.FILL_FIELD,
        element_id=ref,
        document_field_ref="doc_field_1",
        reason="Validated semantic mapping.",
        confidence=ConfidenceLevel.HIGH,
    )


def _validated(scheme: str, domain: str = "example.test") -> ValidatedURL:
    return ValidatedURL(
        url=f"{scheme}://reports.{domain}/login",
        scheme=scheme,
        hostname=f"reports.{domain}",
        port=443 if scheme == "https" else 80,
        domain=domain,
    )


class InteractionSafetyTests(unittest.TestCase):
    def test_sensitive_field_is_blocked_on_http(self) -> None:
        validator = InteractionSafetyValidator(_store())
        with (
            patch(
                "browser_agent.interaction.validate_public_url",
                return_value=_validated("http"),
            ),
            self.assertRaises(InteractionSafetyError),
        ):
            validator.validate_fill(
                _fill(),
                _observation(),
                current_url="http://reports.example.test/login",
                trusted_domains={"example.test"},
            )

    def test_explicit_legacy_http_opt_in_allows_trusted_form(self) -> None:
        validator = InteractionSafetyValidator(
            _store(),
            allow_insecure_http=True,
        )
        with patch(
            "browser_agent.interaction.validate_public_url",
            return_value=_validated("http"),
        ):
            validator.validate_fill(
                _fill(),
                _observation(),
                current_url="http://reports.example.test/login",
                trusted_domains={"example.test"},
            )

    def test_unknown_cross_domain_form_destination_is_blocked(self) -> None:
        validator = InteractionSafetyValidator(_store())
        with (
            patch(
                "browser_agent.interaction.validate_public_url",
                return_value=_validated("https"),
            ),
            self.assertRaises(InteractionSafetyError),
        ):
            validator.validate_fill(
                _fill(),
                _observation(form_domain="untrusted.test"),
                current_url="https://reports.example.test/login",
                trusted_domains={"example.test"},
            )

    def test_hallucinated_input_reference_is_rejected(self) -> None:
        validator = InteractionSafetyValidator(_store())
        with self.assertRaises(InteractionSafetyError):
            validator.validate_fill(
                _fill("input_99"),
                _observation(),
                current_url="https://reports.example.test/login",
                trusted_domains={"example.test"},
            )

    def test_current_pdf_response_becomes_download_candidate(self) -> None:
        class MediaSession:
            page = object()
            current_document_media_type = "application/pdf"
            has_pending_report_download = False
            pending_report_file_type = None

        class Inspector:
            def inspect(self, _page: object) -> BrowserObservation:
                return _observation()

        with TemporaryDirectory() as directory:
            tools = ControlledBrowserTools(
                MediaSession(),  # type: ignore[arg-type]
                _store(),
                ReportDownloadManager(Path(directory)),
                inspector=Inspector(),  # type: ignore[arg-type]
            )

            observation = tools.inspect_page()

        self.assertEqual(observation.page_type, PageType.REPORT_VIEWER)
        self.assertFalse(observation.authentication_signals.authentication_required)
        self.assertEqual(observation.document_media_type, "application/pdf")
        self.assertFalse(observation.pending_download_detected)
        self.assertEqual(len(observation.download_candidates), 1)
        self.assertEqual(observation.download_candidates[0].element_id, "page_1")
        self.assertEqual(
            observation.download_candidates[0].kind,
            DownloadCandidateKind.CURRENT_DOCUMENT,
        )

    def test_unvalidated_html_viewer_is_not_made_printable(self) -> None:
        class HtmlSession:
            page = object()
            current_document_media_type = "text/html"
            has_pending_report_download = False
            pending_report_file_type = None

        class Inspector:
            def inspect(self, _page: object) -> BrowserObservation:
                return _observation().model_copy(
                    update={
                        "page_type": PageType.REPORT_VIEWER,
                        "authentication_signals": AuthenticationSignals(
                            authentication_required=False,
                            field_count=0,
                            confidence=ConfidenceLevel.LOW,
                        ),
                    }
                )

        with TemporaryDirectory() as directory:
            tools = ControlledBrowserTools(
                HtmlSession(),  # type: ignore[arg-type]
                _store(),
                ReportDownloadManager(Path(directory)),
                inspector=Inspector(),  # type: ignore[arg-type]
            )

            observation = tools.inspect_page()

        self.assertEqual(observation.download_candidates, [])

    def test_unknown_html_child_from_validated_report_action_is_printable(self) -> None:
        class ReportChildSession:
            page = object()
            current_document_media_type = "text/html"
            current_page_from_report_action = True
            has_pending_report_download = False
            pending_report_file_type = None

        class Inspector:
            def inspect(self, _page: object) -> BrowserObservation:
                return _observation().model_copy(
                    update={
                        "page_type": PageType.UNKNOWN,
                        "authentication_signals": AuthenticationSignals(
                            authentication_required=False,
                            field_count=0,
                            confidence=ConfidenceLevel.LOW,
                        ),
                    }
                )

        with TemporaryDirectory() as directory:
            tools = ControlledBrowserTools(
                ReportChildSession(),  # type: ignore[arg-type]
                _store(),
                ReportDownloadManager(Path(directory)),
                inspector=Inspector(),  # type: ignore[arg-type]
            )

            observation = tools.inspect_page()

        self.assertEqual(observation.page_type, PageType.REPORT_VIEWER)
        self.assertEqual(
            observation.download_candidates[0].kind,
            DownloadCandidateKind.PRINTABLE_PAGE,
        )


if __name__ == "__main__":
    unittest.main()
