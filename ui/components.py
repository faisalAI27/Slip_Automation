"""Reusable Streamlit presentation components."""

from html import escape

import streamlit as st

from workflow.state import PROGRESS_STEPS, WorkflowState, step_index


def render_header() -> None:
    with st.container(horizontal_alignment="center", gap="small"):
        st.badge("Simple and secure", icon=":material/verified_user:", color="blue")
        st.title("Get My Lab Report", text_alignment="center")
        st.markdown(
            "Upload or take a clear photo of your hospital or laboratory slip.",
            text_alignment="center",
        )


def render_image_preview(image_data: bytes) -> None:
    st.subheader("2. Check your photo")
    st.image(image_data, caption="Preview of your slip photo", width="stretch")
    st.caption("Your photo is kept temporarily and removed when you start over.")


def render_progress(current_state: WorkflowState, failed: bool = False) -> None:
    current_index = step_index(current_state)
    rows: list[str] = []
    for index, (_, label) in enumerate(PROGRESS_STEPS):
        if failed and index == current_index:
            css_class, marker = "error", "!"
        elif index < current_index or current_state == WorkflowState.COMPLETED:
            css_class, marker = "done", "✓"
        elif index == current_index:
            css_class, marker = "current", "•"
        else:
            css_class, marker = "upcoming", ""
        rows.append(
            f'<div class="progress-row {css_class}" role="listitem">'
            f'<span class="progress-marker" aria-hidden="true">{marker}</span>'
            f"<span>{escape(label)}</span></div>"
        )

    st.html(
        """
        <section class="progress-shell" aria-live="polite">
          <h2 class="progress-title">Getting things ready</h2>
          <p class="progress-intro">Please keep this page open for a moment.</p>
          <div class="progress-list" role="list">
        """
        + "".join(rows)
        + "</div></section>",
    )


def render_understanding_outcome(analysis_status: str) -> None:
    if analysis_status == "not_medical":
        st.warning(
            "This doesn't appear to be a hospital or laboratory slip.",
            icon=":material/document_scanner:",
        )
        return

    st.success("Slip understood", icon=":material/check_circle:")
    st.caption("Scroll down to review the information extracted from your slip.")


def render_error(message: str) -> None:
    st.error(message, icon=":material/error:")


def render_footer() -> None:
    st.html(
        '<p class="footer-note">Phase 2.1 · Extraction details enabled</p>',
    )
