"""Demo-only workflow implementation for exercising the complete UI flow."""

from collections.abc import Iterator
import time

from utils.logger import get_logger
from workflow.state import PROGRESS_STEPS, WorkflowUpdate


logger = get_logger(__name__)


def run_mock_workflow(stage_delay_seconds: float = 0.65) -> Iterator[WorkflowUpdate]:
    """Yield deterministic demo stages.

    Replace this function with a real workflow service in a later project step.
    It performs no OCR, document interpretation, browsing, or report retrieval.
    """
    for state, user_message in PROGRESS_STEPS:
        internal_stage = f"mock:{state.value}"
        logger.info("Mock workflow stage changed: %s", state.value)
        yield WorkflowUpdate(state, user_message, internal_stage)
        time.sleep(stage_delay_seconds)
