import unittest

from workflow.mock_processor import run_mock_workflow
from workflow.state import PROGRESS_STEPS, WorkflowState, step_index


class WorkflowTests(unittest.TestCase):
    def test_mock_processor_yields_declared_steps(self) -> None:
        updates = list(run_mock_workflow(stage_delay_seconds=0))
        self.assertEqual(
            [update.state for update in updates],
            [state for state, _ in PROGRESS_STEPS],
        )
        self.assertTrue(all(update.internal_stage.startswith("mock:") for update in updates))

    def test_completed_marks_all_steps_done(self) -> None:
        self.assertEqual(step_index(WorkflowState.COMPLETED), len(PROGRESS_STEPS))


if __name__ == "__main__":
    unittest.main()
