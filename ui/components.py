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


def render_plan_outcome(planning_status: str) -> None:
    if planning_status == "unsupported":
        st.warning(
            "This document is not suitable for online medical report retrieval.",
            icon=":material/document_scanner:",
        )
        return

    st.success(
        "Your slip is ready for online retrieval.",
        icon=":material/check_circle:",
    )
    st.caption("Browser automation will be added in the next phase.")


def render_browser_outcome() -> None:
    st.success("Report service found.", icon=":material/check_circle:")
    st.caption("The report service is ready for controlled retrieval.")


def render_user_input_required() -> None:
    st.warning(
        "We need clearer organization or portal information before continuing.",
        icon=":material/help:",
    )
    st.caption("Try a clearer, complete photo that includes the organization header.")


def render_download_ready(
    report_count: int = 1,
    *,
    insecure_portal_used: bool = False,
) -> None:
    if report_count > 1:
        st.success(
            f"Your {report_count} latest reports are ready.",
            icon=":material/check_circle:",
        )
        st.caption(
            "View or download each newest-date report below. You can also download "
            "all of them as one ZIP. Temporary copies are removed when you start over."
        )
    else:
        st.success("Your report is ready.", icon=":material/check_circle:")
        st.caption(
            "View or download it below. The temporary copy is removed when you "
            "start over."
        )
    if insecure_portal_used:
        st.warning(
            "The hospital supplied an unencrypted report portal. Information sent "
            "to that website may be exposed in transit.",
            icon=":material/warning:",
        )


def render_verification_required() -> None:
    st.warning(
        "The report website requires a verification step.",
        icon=":material/verified_user:",
    )
    st.caption(
        "For your safety, the app stopped and did not try to solve a CAPTCHA, "
        "enter a one-time code, or bypass verification."
    )
    st.caption(
        "If no verification challenge was visible, try retrieval again once."
    )


def render_report_not_found() -> None:
    st.warning("No downloadable report was found.", icon=":material/search_off:")
    st.caption(
        "The website may not have published the report yet, or it may require a "
        "different report-access route."
    )


def render_error(message: str) -> None:
    st.error(message, icon=":material/error:")


def render_footer() -> None:
    st.html(
        '<p class="footer-note">Phase 5 · Controlled report retrieval</p>',
    )
