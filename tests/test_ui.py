import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest

from tests.test_result_view import RESULT_PAYLOAD
from ui.styles import APP_CSS
from workflow.state import WorkflowState


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

    def test_phase_three_runs_automatically_after_document_understanding(self) -> None:
        app_path = Path(__file__).resolve().parents[1] / "app.py"
        app = AppTest.from_file(app_path)
        app.session_state["workflow_state"] = WorkflowState.DOCUMENT_UNDERSTOOD
        app.session_state["document_understanding_result"] = RESULT_PAYLOAD

        app.run(timeout=15)

        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["workflow_state"], WorkflowState.PLAN_READY)
        self.assertEqual(app.session_state["workflow_plan"]["status"], "ready")
        self.assertIn(
            "Your slip is ready for online retrieval.",
            [item.value for item in app.success],
        )


if __name__ == "__main__":
    unittest.main()
