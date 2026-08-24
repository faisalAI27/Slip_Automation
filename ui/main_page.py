"""Main Streamlit page orchestration."""

from hashlib import sha256
from pathlib import Path
import uuid

import streamlit as st

from browser_agent.executor import BrowserExecutor
from config.settings import Settings
from document_understanding.models import AnalysisStatus, DocumentUnderstandingResult
from document_understanding.provider import (
    ProviderConfigurationError,
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    create_document_provider,
)
from document_understanding.service import DocumentUnderstandingService
from ui.components import (
    render_browser_outcome,
    render_error,
    render_footer,
    render_header,
    render_image_preview,
    render_progress,
    render_plan_outcome,
    render_user_input_required,
)
from ui.developer_view import (
    render_browser_execution_debug,
    render_document_debug,
    render_workflow_plan_debug,
)
from ui.result_view import render_extracted_document, render_portal_attempt_details
from ui.styles import APP_CSS
from utils.file_utils import (
    ImageTooLargeError,
    InvalidImageError,
    UnsupportedImageError,
    remove_files,
    save_uploaded_image,
)
from utils.logger import get_logger
from workflow.models import ActionType, PlanningStatus, WorkflowPlan
from workflow.planner import WorkflowPlanner
from workflow.state import WorkflowState
from workflow.validation import PlanningValidationError


logger = get_logger(__name__)

DEFAULT_SESSION_VALUES = {
    "uploaded_image": None,
    "uploaded_fingerprint": None,
    "temporary_image_path": None,
    "workflow_state": WorkflowState.IDLE,
    "processing_status": None,
    "error_state": None,
    "resulting_file_path": None,
    "document_understanding_result": None,
    "workflow_plan": None,
    "browser_action_result": None,
    "developer_mode_enabled": False,
    "document_processing_stage": None,
    "planning_stage": None,
    "browser_execution_stage": None,
    "portal_recovery_error": None,
    "internal_error": None,
}

RECOVERABLE_BROWSER_ERRORS = {
    "browser_timeout",
    "unsafe_navigation",
    "navigation_error",
    "search_execution_error",
    "page_inspection_error",
}


def _initialize_session() -> None:
    for key, value in DEFAULT_SESSION_VALUES.items():
        if key not in st.session_state:
            st.session_state[key] = value
    if "run_session_id" not in st.session_state:
        st.session_state.run_session_id = uuid.uuid4().hex[:10]


def _set_state(state: WorkflowState) -> None:
    previous = st.session_state.workflow_state
    st.session_state.workflow_state = state
    logger.info("Workflow state transition: %s -> %s", previous.value, state.value)


def _run_file_paths() -> list[Path | None]:
    image_path = st.session_state.temporary_image_path
    result_path = st.session_state.resulting_file_path
    return [Path(image_path) if image_path else None, Path(result_path) if result_path else None]


def _reset_run(settings: Settings) -> None:
    remove_files(_run_file_paths(), settings.temp_dir)
    developer_mode_enabled = st.session_state.get("developer_mode_enabled", False)
    for key in list(DEFAULT_SESSION_VALUES) + [
        "photo_input_method",
        "upload_slip",
        "camera_slip",
        "show_raw_document_json",
        "show_raw_workflow_plan_json",
        "show_raw_browser_observation_json",
        "manual_portal_url",
        "run_session_id",
    ]:
        st.session_state.pop(key, None)
    _initialize_session()
    st.session_state.developer_mode_enabled = developer_mode_enabled
    logger.info("Run session reset")
    st.rerun()


def _accept_selected_image(selected_file: object, settings: Settings) -> None:
    file_data = selected_file.getvalue()  # Streamlit UploadedFile interface
    fingerprint = sha256(file_data).hexdigest()
    if fingerprint == st.session_state.uploaded_fingerprint:
        return

    remove_files(_run_file_paths(), settings.temp_dir)
    try:
        stored_path = save_uploaded_image(
            file_data=file_data,
            original_name=selected_file.name,
            temp_dir=settings.temp_dir,
            max_upload_mb=settings.max_upload_mb,
        )
    except UnsupportedImageError:
        st.session_state.error_state = "Please upload a JPG, JPEG, or PNG image."
        st.session_state.uploaded_image = None
        st.session_state.uploaded_fingerprint = None
        st.session_state.temporary_image_path = None
        st.session_state.resulting_file_path = None
        _set_state(WorkflowState.IDLE)
        logger.warning("Upload rejected: unsupported image type")
        return
    except ImageTooLargeError:
        st.session_state.error_state = (
            f"This photo is too large. Please choose one under {settings.max_upload_mb} MB."
        )
        st.session_state.uploaded_image = None
        st.session_state.uploaded_fingerprint = None
        st.session_state.temporary_image_path = None
        st.session_state.resulting_file_path = None
        _set_state(WorkflowState.IDLE)
        logger.warning("Upload rejected: image exceeded size limit")
        return
    except InvalidImageError:
        st.session_state.error_state = (
            "This image could not be opened. Please choose another photo."
        )
        st.session_state.uploaded_image = None
        st.session_state.uploaded_fingerprint = None
        st.session_state.temporary_image_path = None
        st.session_state.resulting_file_path = None
        _set_state(WorkflowState.IDLE)
        logger.warning("Upload rejected: invalid image")
        return

    st.session_state.uploaded_image = file_data
    st.session_state.uploaded_fingerprint = fingerprint
    st.session_state.temporary_image_path = str(stored_path)
    st.session_state.resulting_file_path = None
    st.session_state.document_understanding_result = None
    st.session_state.workflow_plan = None
    st.session_state.browser_action_result = None
    st.session_state.error_state = None
    st.session_state.internal_error = None
    st.session_state.planning_stage = None
    st.session_state.browser_execution_stage = None
    st.session_state.portal_recovery_error = None
    st.session_state.processing_status = "Photo ready"
    _set_state(WorkflowState.IMAGE_UPLOADED)


def _render_upload_area(settings: Settings) -> bool:
    st.subheader("1. Add your slip photo")
    st.caption("Keep the full slip in view and make sure the writing is clear.")

    input_method = st.segmented_control(
        "How would you like to add it?",
        options=["Upload photo", "Use camera"],
        default="Upload photo",
        required=True,
        key="photo_input_method",
        width="stretch",
    )

    uploaded_file = None
    camera_file = None
    if input_method == "Use camera":
        st.caption("Your camera starts only after you choose this option.")
        camera_file = st.camera_input(
            "Take a clear photo of your slip",
            key="camera_slip",
            resolution="1080p",
            width="stretch",
        )
    else:
        uploaded_file = st.file_uploader(
            "Choose a photo from your phone or computer",
            type=["jpg", "jpeg", "png"],
            key="upload_slip",
        )

    selected_file = camera_file or uploaded_file
    if selected_file is not None:
        _accept_selected_image(selected_file, settings)
    elif st.session_state.workflow_state == WorkflowState.IMAGE_UPLOADED:
        remove_files(_run_file_paths(), settings.temp_dir)
        for key in ("uploaded_image", "uploaded_fingerprint", "temporary_image_path"):
            st.session_state[key] = None
        _set_state(WorkflowState.IDLE)

    if st.session_state.error_state:
        render_error(st.session_state.error_state)

    if st.session_state.uploaded_image:
        render_image_preview(st.session_state.uploaded_image)
        return st.button(
            "Get report",
            type="primary",
            icon=":material/search:",
            width="stretch",
            disabled=False,
        )
    return False


def _process_document(settings: Settings, area: object) -> None:
    area.empty()
    progress_area = st.empty()
    _set_state(WorkflowState.PROCESSING_DOCUMENT)
    st.session_state.processing_status = "Reading your slip"
    st.session_state.document_processing_stage = "document_analysis:running"

    try:
        provider = create_document_provider(settings)
        with progress_area.container():
            render_progress(WorkflowState.PROCESSING_DOCUMENT)
            with st.spinner(
                "Analyzing locally on this Mac. The first scan may take a few minutes.",
                show_time=True,
                width="stretch",
            ):
                result = DocumentUnderstandingService(provider).analyze(
                    Path(st.session_state.temporary_image_path)
                )
        st.session_state.document_understanding_result = result.model_dump(mode="json")
        st.session_state.document_processing_stage = "document_analysis:complete"

        if result.analysis_status == AnalysisStatus.UNCLEAR:
            st.session_state.error_state = (
                "We couldn't clearly read this slip. Please take a clearer photo and try again."
            )
            st.session_state.processing_status = "Slip could not be read clearly"
            _set_state(WorkflowState.FAILED)
        else:
            st.session_state.error_state = None
            st.session_state.processing_status = "Slip understood"
            _set_state(WorkflowState.DOCUMENT_UNDERSTOOD)
        st.rerun()
    except ProviderConfigurationError as exc:
        logger.warning("Document analysis configuration error")
        st.session_state.error_state = "Document analysis is not configured yet."
        st.session_state.internal_error = str(exc)
        st.session_state.processing_status = "Configuration required"
        st.session_state.document_processing_stage = "document_analysis:configuration_error"
        _set_state(WorkflowState.FAILED)
        st.rerun()
    except ProviderTimeoutError as exc:
        logger.warning("Document analysis timed out")
        st.session_state.error_state = (
            "Local analysis took too long. Please try once more and keep only one app tab open."
        )
        st.session_state.internal_error = str(exc)
        st.session_state.processing_status = "Document analysis timed out"
        st.session_state.document_processing_stage = "document_analysis:timeout"
        _set_state(WorkflowState.FAILED)
        st.rerun()
    except ProviderUnavailableError as exc:
        logger.warning("Document analysis provider is unavailable")
        if settings.document_ai_provider.strip().lower() == "ollama":
            st.session_state.error_state = (
                "Local document analysis isn't running. Please start Ollama and try again."
            )
        else:
            st.session_state.error_state = (
                "We couldn't connect to the document service. Please try again."
            )
        st.session_state.internal_error = str(exc)
        st.session_state.processing_status = "Service unavailable"
        st.session_state.document_processing_stage = "document_analysis:service_error"
        _set_state(WorkflowState.FAILED)
        st.rerun()
    except ProviderResponseError as exc:
        logger.warning("Document analysis provider returned an unusable response")
        st.session_state.error_state = "We couldn't complete the process. Please try again."
        st.session_state.internal_error = str(exc)
        st.session_state.processing_status = "Document analysis failed"
        st.session_state.document_processing_stage = "document_analysis:response_error"
        _set_state(WorkflowState.FAILED)
        st.rerun()
    except Exception as exc:  # Never expose or log sensitive document content.
        logger.error("Unexpected document analysis failure: %s", type(exc).__name__)
        st.session_state.error_state = "We couldn't complete the process. Please try again."
        st.session_state.internal_error = type(exc).__name__
        st.session_state.processing_status = "Document analysis failed"
        st.session_state.document_processing_stage = "document_analysis:unexpected_error"
        _set_state(WorkflowState.FAILED)
        st.rerun()


def _plan_workflow(area: object) -> None:
    area.empty()
    progress_area = st.empty()
    _set_state(WorkflowState.DISCOVERING_PORTAL)
    st.session_state.processing_status = "Preparing the next step"
    st.session_state.planning_stage = "workflow_planning:running"

    try:
        result = DocumentUnderstandingResult.model_validate(
            st.session_state.document_understanding_result
        )
        with progress_area.container():
            render_progress(WorkflowState.DISCOVERING_PORTAL)
            with st.spinner(
                "Preparing a safe retrieval plan. No website will be opened.",
                show_time=True,
                width="stretch",
            ):
                plan = WorkflowPlanner().plan(result)

        st.session_state.workflow_plan = plan.model_dump(mode="json")
        st.session_state.planning_stage = "workflow_planning:complete"
        st.session_state.internal_error = None
        st.session_state.error_state = None
        if plan.status == PlanningStatus.USER_INPUT_REQUIRED:
            st.session_state.processing_status = "More information required"
            _set_state(WorkflowState.USER_INPUT_REQUIRED)
        elif plan.status == PlanningStatus.UNSUPPORTED:
            st.session_state.processing_status = "Unsupported document"
            _set_state(WorkflowState.UNSUPPORTED)
        elif plan.status == PlanningStatus.FAILED:
            st.session_state.error_state = "We couldn't prepare the next step. Please try again."
            st.session_state.processing_status = "Workflow planning failed"
            _set_state(WorkflowState.FAILED)
        elif plan.status in {PlanningStatus.READY, PlanningStatus.SEARCH_REQUIRED}:
            st.session_state.processing_status = "Retrieval plan ready"
            _set_state(WorkflowState.PLAN_READY)
        else:
            raise PlanningValidationError("Unsupported planning outcome.")
        st.rerun()
    except (PlanningValidationError, ValueError, TypeError) as exc:
        logger.error("Workflow planning failed validation: %s", type(exc).__name__)
        st.session_state.error_state = "We couldn't prepare the next step. Please try again."
        st.session_state.internal_error = type(exc).__name__
        st.session_state.processing_status = "Workflow planning failed"
        st.session_state.planning_stage = "workflow_planning:validation_error"
        _set_state(WorkflowState.FAILED)
        st.rerun()
    except Exception as exc:  # Never log the plan or sensitive document values.
        logger.error("Unexpected workflow planning failure: %s", type(exc).__name__)
        st.session_state.error_state = "We couldn't prepare the next step. Please try again."
        st.session_state.internal_error = type(exc).__name__
        st.session_state.processing_status = "Workflow planning failed"
        st.session_state.planning_stage = "workflow_planning:unexpected_error"
        _set_state(WorkflowState.FAILED)
        st.rerun()


def _browser_error_message(error_type: str | None) -> str:
    return {
        "browser_configuration_error": "Browser setup is incomplete.",
        "browser_launch_error": "The secure browser could not be started.",
        "browser_timeout": "The report website took too long to respond. Please try again.",
        "unsafe_navigation": "This website could not be opened safely.",
        "unsafe_search_query": "The report-service search could not be performed safely.",
        "navigation_error": "We couldn't open the report service automatically.",
        "search_execution_error": "We couldn't find the report service automatically.",
        "page_inspection_error": "The report website could not be understood safely.",
        "non_actionable_plan": "This document cannot continue to website inspection.",
    }.get(error_type, "We couldn't inspect the report service. Please try again.")


def _suggested_portal_url() -> str:
    plan_data = st.session_state.workflow_plan
    if not plan_data:
        return ""
    try:
        plan = WorkflowPlan.model_validate(plan_data)
    except (ValueError, TypeError):
        return ""
    action = plan.required_next_action
    return action.target or "" if action.type == ActionType.OPEN_URL else ""


def _use_manual_portal_url(value: str) -> None:
    try:
        result = DocumentUnderstandingResult.model_validate(
            st.session_state.document_understanding_result
        )
        plan = WorkflowPlanner().plan_user_provided_url(result, value)
    except (PlanningValidationError, ValueError, TypeError):
        st.session_state.portal_recovery_error = (
            "Enter a complete public website, for example https://hospital.example."
        )
        return

    st.session_state.workflow_plan = plan.model_dump(mode="json")
    st.session_state.browser_action_result = None
    st.session_state.error_state = None
    st.session_state.internal_error = None
    st.session_state.portal_recovery_error = None
    st.session_state.planning_stage = "workflow_planning:user_provided_url"
    st.session_state.browser_execution_stage = None
    st.session_state.processing_status = "Website ready to check"
    _set_state(WorkflowState.PLAN_READY)
    st.rerun()


def _render_portal_recovery() -> None:
    browser_data = st.session_state.browser_action_result
    if not browser_data:
        return
    error_type = browser_data.get("error_type")
    if error_type not in RECOVERABLE_BROWSER_ERRORS:
        return

    if "manual_portal_url" not in st.session_state:
        st.session_state.manual_portal_url = _suggested_portal_url()

    with st.container(border=True, gap="small"):
        st.subheader("Check a website only if needed")
        st.caption(
            "Automatic discovery has already finished. If you know the hospital or "
            "laboratory website, correct the address below; otherwise scan another slip."
        )
        with st.form("manual_portal_recovery", border=False):
            portal_url = st.text_input(
                "Hospital or laboratory website",
                key="manual_portal_url",
                placeholder="https://hospital.example",
                help="Use a public HTTP or HTTPS website. Patient details are not required.",
            )
            submitted = st.form_submit_button(
                "Check this website",
                type="primary",
                icon=":material/travel_explore:",
                width="stretch",
            )
        if submitted:
            _use_manual_portal_url(portal_url)
        if st.session_state.portal_recovery_error:
            render_error(st.session_state.portal_recovery_error)


def _execute_browser(settings: Settings, area: object) -> None:
    area.empty()
    progress_area = st.empty()
    _set_state(WorkflowState.NAVIGATING_PORTAL)
    st.session_state.browser_execution_stage = "browser_execution:running"

    try:
        plan = WorkflowPlan.model_validate(st.session_state.workflow_plan)
        if plan.status not in {PlanningStatus.READY, PlanningStatus.SEARCH_REQUIRED}:
            raise ValueError("Non-actionable plan reached browser execution.")
        searching = plan.required_next_action.type == ActionType.SEARCH_WEB
        st.session_state.processing_status = (
            "Finding the official report service"
            if searching
            else "Opening the report service"
        )
        with progress_area.container():
            render_progress(WorkflowState.NAVIGATING_PORTAL)
            with st.spinner(
                (
                    "Finding the official report service. No patient details are searched."
                    if searching
                    else "Opening and inspecting the report service without submitting anything."
                ),
                show_time=True,
                width="stretch",
            ):
                execution = BrowserExecutor.from_settings(settings).execute(plan)

        st.session_state.browser_action_result = execution.model_dump(mode="json")
        if execution.success:
            st.session_state.browser_execution_stage = "browser_execution:complete"
            st.session_state.processing_status = "Report service found"
            st.session_state.error_state = None
            st.session_state.internal_error = None
            _set_state(WorkflowState.BROWSER_OBSERVATION_READY)
        else:
            st.session_state.browser_execution_stage = "browser_execution:controlled_error"
            st.session_state.processing_status = "Website inspection stopped"
            st.session_state.error_state = _browser_error_message(execution.error_type)
            st.session_state.internal_error = execution.error_type
            _set_state(WorkflowState.FAILED)
        st.rerun()
    except (ValueError, TypeError) as exc:
        logger.error("Browser execution input failed validation: %s", type(exc).__name__)
        st.session_state.error_state = "We couldn't inspect the report service. Please try again."
        st.session_state.internal_error = type(exc).__name__
        st.session_state.processing_status = "Website inspection failed"
        st.session_state.browser_execution_stage = "browser_execution:validation_error"
        _set_state(WorkflowState.FAILED)
        st.rerun()
    except Exception as exc:  # Never log page content, form data, or document values.
        logger.error("Unexpected browser execution failure: %s", type(exc).__name__)
        st.session_state.error_state = "We couldn't inspect the report service. Please try again."
        st.session_state.internal_error = type(exc).__name__
        st.session_state.processing_status = "Website inspection failed"
        st.session_state.browser_execution_stage = "browser_execution:unexpected_error"
        _set_state(WorkflowState.FAILED)
        st.rerun()


def _render_developer_details(settings: Settings) -> None:
    if not settings.debug_mode:
        return
    with st.expander("Developer details", expanded=False):
        st.toggle("Enable debug information", key="developer_mode_enabled")
        if st.session_state.developer_mode_enabled:
            st.json(
                {
                    "workflow_state": st.session_state.workflow_state.value,
                    "temporary_image_path": st.session_state.temporary_image_path,
                    "resulting_file_path": st.session_state.resulting_file_path,
                    "processing_status": st.session_state.processing_status,
                    "document_stage": st.session_state.document_processing_stage,
                    "planning_stage": st.session_state.planning_stage,
                    "browser_stage": st.session_state.browser_execution_stage,
                    "error": st.session_state.error_state,
                    "internal_error": st.session_state.internal_error,
                    "run_session_id": st.session_state.run_session_id,
                    "environment": settings.app_env,
                    "document_provider": settings.document_ai_provider,
                    "document_model": settings.document_ai_model,
                    "browser_headless": settings.browser_headless,
                }
            )
            if st.session_state.document_understanding_result:
                render_document_debug(st.session_state.document_understanding_result)
            if st.session_state.workflow_plan:
                render_workflow_plan_debug(st.session_state.workflow_plan)
            if st.session_state.browser_action_result:
                render_browser_execution_debug(st.session_state.browser_action_result)


def render_app(settings: Settings) -> None:
    st.set_page_config(page_title="Get My Lab Report", layout="centered")
    st.html(APP_CSS)
    _initialize_session()
    render_header()

    state = st.session_state.workflow_state
    main_area = st.empty()
    if state in {WorkflowState.IDLE, WorkflowState.IMAGE_UPLOADED}:
        with main_area.container():
            should_process = _render_upload_area(settings)
        if should_process:
            _process_document(settings, main_area)
    elif state == WorkflowState.DOCUMENT_UNDERSTOOD:
        _plan_workflow(main_area)
    elif state == WorkflowState.PLAN_READY:
        _execute_browser(settings, main_area)
    elif state == WorkflowState.BROWSER_OBSERVATION_READY:
        with main_area.container():
            result_data = st.session_state.document_understanding_result or {}
            render_browser_outcome()
            render_extracted_document(result_data)
            st.caption(
                "The service was inspected without submitting forms, entering credentials, "
                "clicking report actions, or downloading files."
            )
            if st.button(
                "Scan another slip", icon=":material/restart_alt:", width="stretch"
            ):
                _reset_run(settings)
    elif state == WorkflowState.UNSUPPORTED:
        with main_area.container():
            result_data = st.session_state.document_understanding_result or {}
            render_plan_outcome("unsupported")
            if result_data:
                render_extracted_document(result_data)
            if st.button(
                "Scan another slip", icon=":material/restart_alt:", width="stretch"
            ):
                _reset_run(settings)
    elif state == WorkflowState.USER_INPUT_REQUIRED:
        with main_area.container():
            render_user_input_required()
            result_data = st.session_state.document_understanding_result or {}
            if result_data:
                render_extracted_document(result_data)
            if st.button(
                "Scan another slip", icon=":material/restart_alt:", width="stretch"
            ):
                _reset_run(settings)
    elif state == WorkflowState.FAILED:
        with main_area.container():
            render_error(st.session_state.error_state)
            result_data = st.session_state.document_understanding_result or {}
            if result_data:
                render_portal_attempt_details(
                    result_data,
                    st.session_state.workflow_plan,
                    st.session_state.browser_action_result,
                )
            _render_portal_recovery()
            st.write("")
            if st.button(
                "Scan another slip", icon=":material/restart_alt:", width="stretch"
            ):
                _reset_run(settings)
    else:
        with main_area.container():
            render_progress(state)

    _render_developer_details(settings)
    render_footer()
