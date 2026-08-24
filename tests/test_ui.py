import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from browser_agent.models import (
    AuthenticationSignals,
    BrowserActionResult,
    BrowserObservation,
    PageType,
    VerificationSignals,
)
from document_understanding.models import ConfidenceLevel
from streamlit.testing.v1 import AppTest

from tests.test_result_view import RESULT_PAYLOAD
from ui.styles import APP_CSS
from workflow.state import WorkflowState
from workflow.models import ActionType
from workflow.planner import WorkflowPlanner
from document_understanding.models import DocumentUnderstandingResult


def _browser_result() -> BrowserActionResult:
    observation = BrowserObservation(
        final_url="https://example.test/reports",
        final_domain="example.test",
        page_title="Online reports",
        page_type=PageType.REPORT_LOGIN_PAGE,
        visible_text_summary="Online reports",
        forms=[],
        input_fields=[],
        buttons=[],
        links=[],
        download_candidates=[],
        authentication_signals=AuthenticationSignals(
            authentication_required=False,
            field_count=0,
            confidence=ConfidenceLevel.LOW,
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
    return BrowserActionResult(
        action_type=ActionType.OPEN_URL,
        success=True,
        requested_target_type="url",
        requested_target="https://example.test/reports",
        final_url=observation.final_url,
        final_domain=observation.final_domain,
        redirect_occurred=False,
        redirects=[],
        observation=observation,
        search_observation=None,
        warnings=[],
        error_type=None,
        error_message=None,
    )


class UserInterfaceTests(unittest.TestCase):
    def test_css_does_not_override_streamlit_icon_fonts(self) -> None:
        self.assertNotIn('[class*="st-"]', APP_CSS)

    def test_camera_is_opt_in(self) -> None:
        app_path = Path(__file__).resolve().parents[1] / "app.py"
        app = AppTest.from_file(app_path).run(timeout=15)

        self.assertFalse(app.exception)
        self.assertEqual(len(app.get("file_uploader")), 1)
        self.assertEqual(len(app.get("camera_input")), 0)

        app.get("button_group")[0].set_value("Use camera").run(timeout=15)

        self.assertFalse(app.exception)
        self.assertEqual(len(app.get("file_uploader")), 0)
        self.assertEqual(len(app.get("camera_input")), 1)

    def test_phase_four_runs_automatically_after_document_understanding(self) -> None:
        app_path = Path(__file__).resolve().parents[1] / "app.py"
        app = AppTest.from_file(app_path)
        app.session_state["workflow_state"] = WorkflowState.DOCUMENT_UNDERSTOOD
        app.session_state["document_understanding_result"] = RESULT_PAYLOAD

        with patch("ui.main_page.BrowserExecutor.from_settings") as browser_factory:
            browser_factory.return_value.execute.return_value = _browser_result()
            app.run(timeout=15)

        self.assertFalse(app.exception)
        self.assertEqual(
            app.session_state["workflow_state"],
            WorkflowState.BROWSER_OBSERVATION_READY,
        )
        self.assertEqual(app.session_state["workflow_plan"]["status"], "ready")
        self.assertTrue(app.session_state["browser_action_result"]["success"])
        self.assertIn(
            "Report service found.",
            [item.value for item in app.success],
        )

    def test_unsupported_plan_does_not_launch_browser(self) -> None:
        app_path = Path(__file__).resolve().parents[1] / "app.py"
        payload = deepcopy(RESULT_PAYLOAD)
        payload["analysis_status"] = "not_medical"
        app = AppTest.from_file(app_path)
        app.session_state["workflow_state"] = WorkflowState.DOCUMENT_UNDERSTOOD
        app.session_state["document_understanding_result"] = payload

        with patch("ui.main_page.BrowserExecutor.from_settings") as browser_factory:
            app.run(timeout=15)

        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["workflow_state"], WorkflowState.UNSUPPORTED)
        browser_factory.assert_not_called()

    def test_developer_view_renders_structured_browser_observation(self) -> None:
        payload = _browser_result().model_dump(mode="json")
        source = (
            "from ui.developer_view import render_browser_execution_debug\n"
            f"render_browser_execution_debug({payload!r})\n"
        )

        app = AppTest.from_string(source).run(timeout=15)

        self.assertFalse(app.exception)
        subheaders = [item.value for item in app.subheader]
        self.assertIn("Browser execution", subheaders)
        self.assertIn("Page observation", subheaders)
        self.assertIn("Input fields", subheaders)
        self.assertIn("Buttons", subheaders)
        self.assertIn("Links", subheaders)
        self.assertIn("Download candidates", subheaders)

    def test_browser_failure_offers_prefilled_optional_url_recovery(self) -> None:
        app_path = Path(__file__).resolve().parents[1] / "app.py"
        result = DocumentUnderstandingResult.model_validate(RESULT_PAYLOAD)
        plan = WorkflowPlanner().plan(result)
        failure = {
            "action_type": "open_url",
            "success": False,
            "requested_target_type": "url",
            "requested_target": "https://www.example.test/",
            "final_url": None,
            "final_domain": None,
            "redirect_occurred": False,
            "redirects": [],
            "observation": None,
            "search_observation": None,
            "warnings": [],
            "error_type": "unsafe_navigation",
            "error_message": "The destination hostname could not be verified.",
        }
        app = AppTest.from_file(app_path)
        app.session_state["workflow_state"] = WorkflowState.FAILED
        app.session_state["document_understanding_result"] = RESULT_PAYLOAD
        app.session_state["workflow_plan"] = plan.model_dump(mode="json")
        app.session_state["browser_action_result"] = failure
        app.session_state["error_state"] = "This website could not be opened safely."

        app.run(timeout=15)

        self.assertFalse(app.exception)
        self.assertEqual(len(app.text_input), 1)
        self.assertEqual(app.text_input[0].value, "https://www.example.test/")
        self.assertTrue(
            any("Check a website only if needed" in item.value for item in app.subheader)
        )

        app.text_input[0].set_value("reports.example.test")
        with patch("ui.main_page.BrowserExecutor.from_settings") as browser_factory:
            browser_factory.return_value.execute.return_value = _browser_result()
            app.button[0].click().run(timeout=15)

        self.assertFalse(app.exception)
        self.assertEqual(
            app.session_state["workflow_state"],
            WorkflowState.BROWSER_OBSERVATION_READY,
        )
        self.assertEqual(
            app.session_state["workflow_plan"]["portal_strategy"],
            "user_provided_url",
        )
        self.assertEqual(
            app.session_state["workflow_plan"]["required_next_action"]["target"],
            "https://reports.example.test/",
        )


if __name__ == "__main__":
    unittest.main()
