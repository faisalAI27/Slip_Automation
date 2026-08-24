"""Reusable Streamlit presentation components."""

from html import escape
import mimetypes
from pathlib import Path

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


def render_result(file_path: Path) -> None:
    st.html(
        """
        <section class="result-shell">
          <div class="result-eyebrow">Ready</div>
          <h2 class="result-title">Report Ready</h2>
          <p class="result-copy">Your test file is ready to view or download.</p>
          <div class="demo-badge"><strong>Demo only:</strong> This is a sample file for testing the interface. No real report was retrieved.</div>
        </section>
        """,
    )

    mime_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    st.download_button(
        "Download report",
        data=file_path.read_bytes(),
        file_name="demo-lab-report.txt",
        mime=mime_type,
        type="primary",
        icon=":material/download:",
        width="stretch",
    )
    if st.button("View report", icon=":material/visibility:", width="stretch"):
        st.session_state.show_report_preview = not st.session_state.get(
            "show_report_preview", False
        )

    if st.session_state.get("show_report_preview", False):
        st.text_area(
            "Demo report preview",
            value=file_path.read_text(encoding="utf-8"),
            height=210,
            disabled=True,
        )


def render_error(message: str) -> None:
    st.error(message, icon=":material/error:")


def render_footer() -> None:
    st.html(
        '<p class="footer-note">Step 1 demo · No medical processing is performed</p>',
    )
