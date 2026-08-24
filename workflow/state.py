"""UI-independent workflow state definitions."""

from dataclasses import dataclass
from enum import Enum


class WorkflowState(str, Enum):
    IDLE = "idle"
    IMAGE_UPLOADED = "image_uploaded"
    PROCESSING_DOCUMENT = "processing_document"
    DOCUMENT_UNDERSTOOD = "document_understood"
    DISCOVERING_PORTAL = "discovering_portal"
    PLAN_READY = "plan_ready"
    NAVIGATING_PORTAL = "navigating_portal"
    BROWSER_OBSERVATION_READY = "browser_observation_ready"
    RETRIEVING_REPORT = "retrieving_report"
    DOWNLOAD_READY = "download_ready"
    VERIFICATION_REQUIRED = "verification_required"
    REPORT_NOT_FOUND = "report_not_found"
    USER_INPUT_REQUIRED = "user_input_required"
    UNSUPPORTED = "unsupported"
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
    (WorkflowState.DISCOVERING_PORTAL, "Preparing the next step"),
    (WorkflowState.NAVIGATING_PORTAL, "Opening the report service"),
    (WorkflowState.RETRIEVING_REPORT, "Retrieving your report"),
)


def step_index(state: WorkflowState) -> int:
    states = [step_state for step_state, _ in PROGRESS_STEPS]
    if state in {
        WorkflowState.BROWSER_OBSERVATION_READY,
        WorkflowState.DOWNLOAD_READY,
        WorkflowState.VERIFICATION_REQUIRED,
        WorkflowState.REPORT_NOT_FOUND,
        WorkflowState.UNSUPPORTED,
        WorkflowState.COMPLETED,
    }:
        return len(states)
    if state == WorkflowState.PLAN_READY:
        return states.index(WorkflowState.NAVIGATING_PORTAL)
    if state == WorkflowState.USER_INPUT_REQUIRED:
        return states.index(WorkflowState.RETRIEVING_REPORT)
    if state == WorkflowState.FAILED:
        return len(states) - 1
    if state in states:
        return states.index(state)
    return 0
