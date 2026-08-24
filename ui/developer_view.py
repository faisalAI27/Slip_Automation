"""Sensitive local-only developer presentation for understanding and planning."""

import streamlit as st

from document_understanding.models import DocumentUnderstandingResult
from workflow.models import WorkflowPlan


def _display(value: object | None) -> str:
    if value is None or value == "":
        return "—"
    return str(value).replace("_", " ")


def render_document_debug(result_data: dict[str, object]) -> None:
    result = DocumentUnderstandingResult.model_validate(result_data)
    st.warning(
        "Sensitive debug information: this section may contain patient details, "
        "identifiers, and access credentials. Do not share screenshots.",
        icon=":material/privacy_tip:",
    )

    st.subheader("Document")
    st.table(
        [
            {
                "Type": _display(result.document_type),
                "Purpose": _display(result.purpose),
                "Likely action": _display(result.likely_action),
                "Confidence": _display(result.overall_confidence.value),
                "Status": _display(result.analysis_status.value),
            }
        ]
    )

    st.subheader("Organization")
    if result.organization:
        st.table(
            [
                {
                    "Name": _display(result.organization.name),
                    "Type": _display(result.organization.type.value),
                    "Confidence": _display(result.organization.confidence.value),
                }
            ]
        )
    else:
        st.caption("No organization was identified.")

    st.subheader("URLs")
    if result.urls:
        st.table(
            [
                {
                    "Visible URL": item.url,
                    "Normalized URL": _display(item.normalized_url),
                    "Purpose": _display(item.likely_purpose.value),
                    "Context": _display(item.context),
                    "Confidence": _display(item.confidence.value),
                }
                for item in result.urls
            ]
        )
    else:
        st.caption("No visible URLs were identified.")

    st.subheader("QR codes")
    if result.qr_codes:
        st.table(
            [
                {
                    "Decoded content": item.value,
                    "Type": _display(item.type.value),
                    "Format": _display(item.symbol_format),
                    "Confidence": _display(item.confidence.value),
                }
                for item in result.qr_codes
            ]
        )
    else:
        st.caption("No QR code content was decoded.")

    st.subheader("Extracted fields")
    if result.fields:
        st.dataframe(
            [
                {
                    "Original label": _display(item.label),
                    "Value": item.value,
                    "Semantic type": _display(item.semantic_type.value),
                    "Confidence": _display(item.confidence.value),
                }
                for item in result.fields
            ],
            hide_index=True,
            width="stretch",
        )
    else:
        st.caption("No meaningful fields were extracted.")

    st.subheader("Dates")
    if result.dates:
        st.table(
            [
                {
                    "Label": _display(item.label),
                    "Value": item.value,
                    "Meaning": _display(item.semantic_type.value),
                    "Confidence": _display(item.confidence.value),
                }
                for item in result.dates
            ]
        )
    else:
        st.caption("No contextual dates were extracted.")

    st.subheader("Instructions")
    if result.instructions:
        for instruction in result.instructions:
            st.markdown(f"- {instruction}")
    else:
        st.caption("No useful instructions were identified.")

    st.subheader("Warnings")
    if result.warnings:
        for warning in result.warnings:
            st.markdown(f"- {warning}")
    else:
        st.caption("No analysis warnings.")

    st.subheader("Short summary")
    st.write(result.raw_summary or "No summary was produced.")

    if st.toggle("Show raw structured JSON", key="show_raw_document_json"):
        st.json(result.model_dump(mode="json"))


def render_workflow_plan_debug(plan_data: dict[str, object]) -> None:
    plan = WorkflowPlan.model_validate(plan_data)
    st.warning(
        "Sensitive workflow information: available fields and the next action may "
        "contain patient identifiers, credentials, or private URLs. Do not share screenshots.",
        icon=":material/privacy_tip:",
    )

    st.subheader("Workflow plan")
    st.caption("Goal")
    st.write(plan.goal)
    st.caption("Planning status")
    st.code(plan.status.value.upper(), language=None)
    st.caption("Selected strategy")
    st.write(_display(plan.portal_strategy.value))

    st.subheader("Portal candidates")
    if plan.portal_candidates:
        st.dataframe(
            [
                {
                    "Source": _display(item.source.value),
                    "URL": item.url,
                    "Purpose": _display(item.likely_purpose.value),
                    "Confidence": _display(item.confidence.value),
                }
                for item in plan.portal_candidates
            ],
            hide_index=True,
            width="stretch",
        )
    else:
        st.caption("No safe portal candidate is currently available.")

    st.subheader("Available fields")
    if plan.available_fields:
        st.dataframe(
            [
                {
                    "Label": _display(item.label),
                    "Value": item.value,
                    "Semantic type": _display(item.semantic_type.value),
                    "Potential use": _display(item.potential_use.value),
                    "Confidence": _display(item.confidence.value),
                }
                for item in plan.available_fields
            ],
            hide_index=True,
            width="stretch",
        )
    else:
        st.caption("No useful document fields are currently available.")

    st.subheader("Next action")
    st.json(plan.required_next_action.model_dump(mode="json"))

    st.subheader("Planner warnings")
    if plan.warnings:
        for warning in plan.warnings:
            st.markdown(f"- {warning}")
    else:
        st.caption("No planner warnings.")

    st.subheader("Planner summary")
    st.write(plan.planner_summary)

    with st.expander("Raw workflow plan JSON", icon=":material/data_object:"):
        st.json(plan.model_dump(mode="json"))
