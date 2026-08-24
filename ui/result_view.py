"""Patient-friendly presentation of validated document extraction results."""

import streamlit as st

from document_understanding.models import (
    ConfidenceLevel,
    DocumentUnderstandingResult,
)
from utils.logger import get_logger


logger = get_logger(__name__)


CONFIDENCE_COLORS = {
    ConfidenceLevel.HIGH: "green",
    ConfidenceLevel.MEDIUM: "blue",
    ConfidenceLevel.LOW: "orange",
    ConfidenceLevel.UNKNOWN: "gray",
}


def _humanize(value: str) -> str:
    return value.replace("_", " ").strip().capitalize() or "Unknown"


def _confidence_badge(confidence: ConfidenceLevel) -> None:
    st.badge(
        f"{_humanize(confidence.value)} confidence",
        icon=":material/check_circle:" if confidence == ConfidenceLevel.HIGH else None,
        color=CONFIDENCE_COLORS[confidence],
    )


def _render_exact_value(value: str) -> None:
    st.code(value, language=None, wrap_lines=True)


def render_extracted_document(result_data: dict[str, object]) -> None:
    """Show exact extracted content without performing any downstream action."""
    result = DocumentUnderstandingResult.model_validate(result_data)
    logger.info(
        "Extraction result view rendered: fields=%d dates=%d urls=%d qr_codes=%d",
        len(result.fields),
        len(result.dates),
        len(result.urls),
        len(result.qr_codes),
    )

    st.subheader("What was extracted")
    st.warning(
        "This information may contain patient details or access codes. "
        "Check it against the original slip before using it.",
        icon=":material/privacy_tip:",
    )

    with st.container(border=True, gap="small"):
        st.markdown("**Document overview**")
        st.caption("Summary")
        st.write(result.raw_summary or "No summary was produced.")

        st.caption("Document type")
        st.write(_humanize(result.document_type))
        _confidence_badge(result.document_type_confidence)

        if result.organization:
            st.caption("Organization")
            st.write(result.organization.name or "Name not identified")
            st.caption(_humanize(result.organization.type.value))

        st.caption("Likely purpose")
        st.write(_humanize(result.purpose))
        st.caption("Likely next action")
        st.write(_humanize(result.likely_action))

    with st.expander(
        f"Extracted fields ({len(result.fields)})",
        expanded=True,
        icon=":material/list_alt:",
    ):
        if result.fields:
            for item in result.fields:
                with st.container(border=True, gap=None):
                    st.caption(item.label or _humanize(item.semantic_type.value))
                    _render_exact_value(item.value)
                    st.caption(
                        f"{_humanize(item.semantic_type.value)} · "
                        f"{_humanize(item.confidence.value)} confidence"
                    )
        else:
            st.caption("No meaningful fields were extracted.")

    if result.dates:
        with st.expander(
            f"Dates ({len(result.dates)})",
            icon=":material/calendar_month:",
        ):
            for item in result.dates:
                with st.container(border=True, gap=None):
                    st.caption(item.label or _humanize(item.semantic_type.value))
                    _render_exact_value(item.value)
                    st.caption(
                        f"{_humanize(item.semantic_type.value)} · "
                        f"{_humanize(item.confidence.value)} confidence"
                    )

    if result.urls or result.qr_codes:
        with st.expander(
            f"Links and QR codes ({len(result.urls) + len(result.qr_codes)})",
            icon=":material/qr_code_2:",
        ):
            st.caption("Detected content is shown only. The app has not opened any link.")
            for item in result.urls:
                st.markdown("**Visible link**")
                _render_exact_value(item.normalized_url or item.url)
                st.caption(
                    f"{_humanize(item.likely_purpose.value)} · "
                    f"{_humanize(item.confidence.value)} confidence"
                )
            for item in result.qr_codes:
                st.markdown("**QR code content**")
                _render_exact_value(item.value)
                st.caption(
                    f"{_humanize(item.type.value)} · "
                    f"{_humanize(item.confidence.value)} confidence"
                )

    if result.instructions:
        with st.expander(
            f"Instructions ({len(result.instructions)})",
            icon=":material/task_alt:",
        ):
            for instruction in result.instructions:
                st.markdown(f"- {instruction}")

    if result.warnings:
        with st.expander(
            f"Items to review ({len(result.warnings)})",
            icon=":material/warning:",
        ):
            for warning in result.warnings:
                st.warning(warning, icon=":material/warning:")

    _confidence_badge(result.overall_confidence)
    st.caption("Overall extraction confidence. Always compare important values with the slip.")
