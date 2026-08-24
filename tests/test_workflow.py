import unittest

from workflow.state import PROGRESS_STEPS, WorkflowState, step_index


class WorkflowTests(unittest.TestCase):
    def test_phase_two_progress_stops_after_understanding(self) -> None:
        self.assertEqual(
            [state for state, _ in PROGRESS_STEPS],
            [WorkflowState.PROCESSING_DOCUMENT, WorkflowState.DOCUMENT_UNDERSTOOD],
        )

    def test_completed_marks_all_declared_steps_done(self) -> None:
        self.assertEqual(step_index(WorkflowState.COMPLETED), len(PROGRESS_STEPS))


if __name__ == "__main__":
    unittest.main()
