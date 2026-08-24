"""UI-independent workflow state definitions."""

from dataclasses import dataclass
from enum import Enum


class WorkflowState(str, Enum):
    IDLE = "idle"
    IMAGE_UPLOADED = "image_uploaded"
    PROCESSING_DOCUMENT = "processing_document"
    DOCUMENT_UNDERSTOOD = "document_understood"
    DISCOVERING_PORTAL = "discovering_portal"
    NAVIGATING_PORTAL = "navigating_portal"
    RETRIEVING_REPORT = "retrieving_report"
    DOWNLOAD_READY = "download_ready"
    USER_INPUT_REQUIRED = "user_input_required"
    FAILED = "failed"
    COMPLETED = "completed"


@dataclass(frozen=True, slots=True)
class WorkflowUpdate:
    state: WorkflowState
    user_message: str
    internal_stage: str


PROGRESS_STEPS: tuple[tuple[WorkflowState, str], ...] = (
    (WorkflowState.PROCESSING_DOCUMENT, "Reading your slip"),
    (WorkflowState.DOCUMENT_UNDERSTOOD, "Understanding the document"),
)


def step_index(state: WorkflowState) -> int:
    states = [step_state for step_state, _ in PROGRESS_STEPS]
    if state in {WorkflowState.COMPLETED}:
        return len(states)
    if state in states:
        return states.index(state)
    return 0
