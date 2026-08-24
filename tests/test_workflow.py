import unittest

from workflow.state import PROGRESS_STEPS, WorkflowState, step_index


class WorkflowTests(unittest.TestCase):
    def test_phase_five_progress_includes_report_retrieval(self) -> None:
        self.assertEqual(
            [state for state, _ in PROGRESS_STEPS],
            [
                WorkflowState.PROCESSING_DOCUMENT,
                WorkflowState.DOCUMENT_UNDERSTOOD,
                WorkflowState.DISCOVERING_PORTAL,
                WorkflowState.NAVIGATING_PORTAL,
                WorkflowState.RETRIEVING_REPORT,
            ],
        )

    def test_completed_marks_all_declared_steps_done(self) -> None:
        self.assertEqual(step_index(WorkflowState.COMPLETED), len(PROGRESS_STEPS))

    def test_plan_ready_precedes_browser_navigation(self) -> None:
        self.assertEqual(
            step_index(WorkflowState.PLAN_READY),
            [state for state, _ in PROGRESS_STEPS].index(
                WorkflowState.NAVIGATING_PORTAL
            ),
        )

    def test_browser_observation_ready_marks_declared_steps_done(self) -> None:
        self.assertEqual(
            step_index(WorkflowState.BROWSER_OBSERVATION_READY), len(PROGRESS_STEPS)
        )


if __name__ == "__main__":
    unittest.main()
