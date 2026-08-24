"""Main Streamlit page orchestration."""

from hashlib import sha256
from pathlib import Path
import uuid

import streamlit as st

from config.settings import Settings
from downloads import create_mock_report
from ui.components import (
    render_error,
    render_footer,
    render_header,
    render_image_preview,
    render_progress,
    render_result,
)
from ui.styles import APP_CSS
from utils.file_utils import (
    ImageTooLargeError,
    InvalidImageError,
    UnsupportedImageError,
    remove_files,
    save_uploaded_image,
)
from utils.logger import get_logger
from workflow.mock_processor import run_mock_workflow
from workflow.state import WorkflowState


logger = get_logger(__name__)

DEFAULT_SESSION_VALUES = {
    "uploaded_image": None,
    "uploaded_fingerprint": None,
    "temporary_image_path": None,
    "workflow_state": WorkflowState.IDLE,
    "processing_status": None,
    "error_state": None,
    "resulting_file_path": None,
    "developer_mode_enabled": False,
    "mock_processing_stage": None,
    "show_report_preview": False,
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
    st.session_state.error_state = None
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


def _process_demo(settings: Settings, area: object) -> None:
    area.empty()
    progress_area = st.empty()
    try:
        for update in run_mock_workflow(settings.mock_stage_delay_seconds):
            _set_state(update.state)
            st.session_state.processing_status = update.user_message
            st.session_state.mock_processing_stage = update.internal_stage
            with progress_area.container():
                render_progress(update.state)

        result_path = create_mock_report(settings.temp_dir)
        st.session_state.resulting_file_path = str(result_path)
        st.session_state.processing_status = "Demo report ready"
        _set_state(WorkflowState.COMPLETED)
        st.rerun()
    except Exception as exc:  # Keep technical details in logs/developer mode only.
        logger.exception("Mock workflow failed")
        st.session_state.error_state = "We couldn't complete the process. Please try again."
        st.session_state.processing_status = "Processing failed"
        st.session_state.mock_processing_stage = f"mock:error:{type(exc).__name__}"
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
                    "mock_stage": st.session_state.mock_processing_stage,
                    "error": st.session_state.error_state,
                    "run_session_id": st.session_state.run_session_id,
                    "environment": settings.app_env,
                }
            )


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
            _process_demo(settings, main_area)
    elif state == WorkflowState.COMPLETED and st.session_state.resulting_file_path:
        with main_area.container():
            render_result(Path(st.session_state.resulting_file_path))
            st.write("")
            if st.button(
                "Scan another slip", icon=":material/restart_alt:", width="stretch"
            ):
                _reset_run(settings)
    elif state == WorkflowState.FAILED:
        with main_area.container():
            render_error(st.session_state.error_state)
            render_progress(state, failed=True)
            st.write("")
            if st.button(
                "Try again", type="primary", icon=":material/refresh:", width="stretch"
            ):
                _reset_run(settings)
    else:
        with main_area.container():
            render_progress(state)

    _render_developer_details(settings)
    render_footer()
