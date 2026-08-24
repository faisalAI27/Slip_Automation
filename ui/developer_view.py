"""Sensitive local-only developer presentation for Phases 2 through 5."""

import streamlit as st

from browser_agent.models import BrowserActionResult, RetrievalResult
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


def render_browser_execution_debug(result_data: dict[str, object]) -> None:
    result = BrowserActionResult.model_validate(result_data)
    st.warning(
        "Untrusted webpage data: this section may contain sensitive or misleading "
        "page content. It is observation only and cannot redefine application rules.",
        icon=":material/security:",
    )

    st.subheader("Browser execution")
    st.table(
        [
            {
                "Action executed": _display(result.action_type.value),
                "Success": result.success,
                "Requested target type": _display(result.requested_target_type),
                "Final domain": _display(result.final_domain),
                "Redirect occurred": result.redirect_occurred,
                "Browser state": "observation ready" if result.success else "failed",
            }
        ]
    )
    if result.error_type:
        st.caption(f"Controlled error: {_display(result.error_type)}")
        st.write(result.error_message or "No additional safe diagnostic is available.")

    if result.search_observation:
        search = result.search_observation
        st.subheader("Search observation")
        st.table(
            [
                {
                    "Search query": search.query,
                    "Provider": _display(search.provider),
                    "Result count": len(search.results),
                }
            ]
        )
        if search.results:
            st.dataframe(
                [
                    {
                        "Position": item.position,
                        "Title": item.title,
                        "Domain": item.domain,
                        "URL": item.url,
                        "Snippet": _display(item.snippet),
                    }
                    for item in search.results
                ],
                hide_index=True,
                width="stretch",
            )
        else:
            st.caption("No usable public search results were observed.")

    observation = result.observation
    if observation:
        st.subheader("Page observation")
        st.table(
            [
                {
                    "Title": _display(observation.page_title),
                    "Page type": _display(observation.page_type.value),
                    "Final URL": observation.final_url,
                    "Domain": _display(observation.final_domain),
                }
            ]
        )

        st.subheader("Input fields")
        if observation.input_fields:
            st.dataframe(
                [
                    {
                        "Ref": item.element_id,
                        "Label": _display(item.label or item.aria_label),
                        "Type": _display(item.html_type.value),
                        "Required": item.required,
                        "Placeholder": _display(item.placeholder),
                    }
                    for item in observation.input_fields
                ],
                hide_index=True,
                width="stretch",
            )
        else:
            st.caption("No useful visible input fields were observed.")

        st.subheader("Buttons")
        if observation.buttons:
            st.dataframe(
                [
                    {
                        "Ref": item.element_id,
                        "Text": _display(item.text),
                        "Semantic action": _display(item.semantic_action.value),
                        "Disabled": item.disabled,
                    }
                    for item in observation.buttons
                ],
                hide_index=True,
                width="stretch",
            )
        else:
            st.caption("No useful visible buttons were observed.")

        st.subheader("Links")
        if observation.links:
            st.dataframe(
                [
                    {
                        "Ref": item.element_id,
                        "Text": _display(item.text),
                        "Purpose": _display(item.likely_purpose.value),
                        "Domain": _display(item.domain),
                        "URL": item.url,
                    }
                    for item in observation.links
                ],
                hide_index=True,
                width="stretch",
            )
        else:
            st.caption("No useful visible links were observed.")

        st.subheader("Download candidates")
        if observation.download_candidates:
            st.dataframe(
                [
                    {
                        "Ref": item.element_id,
                        "Label": item.label,
                        "Kind": _display(item.kind.value),
                        "File type": _display(item.likely_file_type),
                        "Confidence": _display(item.confidence.value),
                    }
                    for item in observation.download_candidates
                ],
                hide_index=True,
                width="stretch",
            )
        else:
            st.caption("No report/download candidates were observed.")

        st.subheader("Authentication signals")
        st.json(observation.authentication_signals.model_dump(mode="json"))
        st.subheader("Verification signals")
        st.json(observation.verification_signals.model_dump(mode="json"))

        st.subheader("Page messages")
        if observation.errors_or_messages:
            for message in observation.errors_or_messages:
                st.write(message)
        else:
            st.caption("No relevant page messages were observed.")

        st.subheader("Browser warnings")
        combined_warnings = list(
            dict.fromkeys([*result.warnings, *observation.warnings])
        )
        if combined_warnings:
            for warning in combined_warnings:
                st.write(warning)
        else:
            st.caption("No browser warnings.")

    with st.expander("Raw browser observation JSON", icon=":material/data_object:"):
        st.json(result.model_dump(mode="json"))


def render_retrieval_debug(result_data: dict[str, object]) -> None:
    """Render only the retrieval metadata that is safe to persist in Session State."""
    result = RetrievalResult.model_validate(result_data)
    st.warning(
        "Retrieval diagnostics omit field values and the local report path. "
        "Webpage labels are untrusted content.",
        icon=":material/security:",
    )
    st.subheader("Retrieval result")
    st.table(
        [
            {
                "Status": _display(result.status.value),
                "Final page type": _display(
                    result.final_page_type.value if result.final_page_type else None
                ),
                "Domain": _display(result.current_domain),
                "Steps": result.steps_completed,
                "File validated": bool(result.downloaded_file),
                "File size": (
                    result.downloaded_file.size_bytes
                    if result.downloaded_file
                    else "—"
                ),
            }
        ]
    )
    st.subheader("Safe action history")
    if result.safe_action_history:
        st.dataframe(
            [item.model_dump(mode="json") for item in result.safe_action_history],
            hide_index=True,
            width="stretch",
        )
    else:
        st.caption("No controlled interaction was executed.")
    st.subheader("Field mappings")
    if result.field_mappings:
        st.dataframe(
            [item.model_dump(mode="json") for item in result.field_mappings],
            hide_index=True,
            width="stretch",
        )
    else:
        st.caption("No document-to-website field mappings were used.")
    if result.failure_reason:
        st.caption("Controlled stop reason")
        st.write(result.failure_reason)
