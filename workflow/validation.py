"""Safety and consistency validation for Phase 3 plans."""

import re
from urllib.parse import urlsplit, urlunsplit

from document_understanding.models import DocumentUnderstandingResult, FieldSemanticType
from workflow.models import (
    ActionType,
    AvailableField,
    PlanningStatus,
    PortalCandidate,
    PortalSource,
    WorkflowPlan,
)


class PlanningValidationError(ValueError):
    """Raised when a generated plan is unsafe or internally inconsistent."""


SENSITIVE_FIELD_TYPES = {
    FieldSemanticType.PATIENT_IDENTIFIER,
    FieldSemanticType.REGISTRATION_IDENTIFIER,
    FieldSemanticType.VISIT_IDENTIFIER,
    FieldSemanticType.REFERENCE_IDENTIFIER,
    FieldSemanticType.SAMPLE_IDENTIFIER,
    FieldSemanticType.REPORT_IDENTIFIER,
    FieldSemanticType.ACCESS_CREDENTIAL,
    FieldSemanticType.PHONE_NUMBER,
    FieldSemanticType.EMAIL,
    FieldSemanticType.PERSON_NAME,
}

EXPECTED_ACTIONS = {
    PlanningStatus.READY: ActionType.OPEN_URL,
    PlanningStatus.SEARCH_REQUIRED: ActionType.SEARCH_WEB,
    PlanningStatus.USER_INPUT_REQUIRED: ActionType.STOP,
    PlanningStatus.UNSUPPORTED: ActionType.STOP,
    PlanningStatus.FAILED: ActionType.STOP,
}


def normalize_navigation_url(value: str) -> str | None:
    candidate = value.strip()
    if candidate.lower().startswith("www."):
        candidate = f"https://{candidate}"
    try:
        parsed = urlsplit(candidate)
        port = parsed.port
    except ValueError:
        return None
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return None
    if parsed.username or parsed.password:
        return None

    hostname = parsed.hostname.lower()
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    default_port = (parsed.scheme.lower() == "http" and port == 80) or (
        parsed.scheme.lower() == "https" and port == 443
    )
    netloc = hostname if port is None or default_port else f"{hostname}:{port}"
    path = parsed.path or "/"
    return urlunsplit((parsed.scheme.lower(), netloc, path, parsed.query, parsed.fragment))


def equivalent_url_key(value: str) -> str | None:
    normalized = normalize_navigation_url(value)
    if normalized is None:
        return None
    parsed = urlsplit(normalized)
    path = parsed.path.rstrip("/") or "/"
    return urlunsplit((parsed.scheme, parsed.netloc, path, parsed.query, "")).casefold()


def deduplicate_portal_candidates(
    candidates: list[PortalCandidate],
) -> list[PortalCandidate]:
    source_priority = {
        PortalSource.PRINTED_URL: 0,
        PortalSource.QR_CODE: 1,
        PortalSource.ORGANIZATION_HOMEPAGE: 2,
        PortalSource.FUTURE_WEB_SEARCH: 3,
    }
    confidence_priority = {"high": 0, "medium": 1, "low": 2, "unknown": 3}
    output: list[PortalCandidate] = []
    seen: set[str] = set()
    ordered = sorted(
        candidates,
        key=lambda item: (
            source_priority[item.source],
            confidence_priority[item.confidence.value],
        ),
    )
    for candidate in ordered:
        normalized = normalize_navigation_url(candidate.url)
        key = equivalent_url_key(candidate.url)
        if normalized is None or key is None or key in seen:
            continue
        seen.add(key)
        output.append(candidate.model_copy(update={"url": normalized}))
    return output


def deduplicate_available_fields(fields: list[AvailableField]) -> list[AvailableField]:
    output: list[AvailableField] = []
    seen: set[tuple[str, str, str]] = set()
    for field in fields:
        value = field.value.strip()
        if not value:
            continue
        semantic_type = field.semantic_type.value
        key = ((field.label or "").casefold(), value.casefold(), semantic_type)
        if key in seen:
            continue
        seen.add(key)
        output.append(field.model_copy(update={"value": value}))
    return output


def sensitive_values(result: DocumentUnderstandingResult) -> list[str]:
    return [
        field.value.strip()
        for field in result.fields
        if field.semantic_type in SENSITIVE_FIELD_TYPES and field.value.strip()
    ]


def _compact_text(value: str) -> str:
    return re.sub(r"[^a-z0-9@]+", "", value.casefold())


def validate_search_query(query: str, prohibited_values: list[str]) -> None:
    clean_query = query.strip()
    if not clean_query:
        raise PlanningValidationError("Search action requires a non-empty query.")
    folded_query = clean_query.casefold()
    compact_query = _compact_text(clean_query)
    for value in prohibited_values:
        clean_value = value.strip()
        if not clean_value:
            continue
        folded_value = clean_value.casefold()
        compact_value = _compact_text(clean_value)
        sensitive_tokens = {
            token for token in re.findall(r"[a-z0-9]+", folded_value) if len(token) >= 4
        }
        if folded_value in folded_query or (
            len(compact_value) >= 3 and compact_value in compact_query
        ) or any(token in folded_query for token in sensitive_tokens):
            raise PlanningValidationError(
                "Search query contains sensitive document information."
            )


def validate_plan(
    plan: WorkflowPlan, result: DocumentUnderstandingResult
) -> WorkflowPlan:
    expected_action = EXPECTED_ACTIONS[plan.status]
    if plan.required_next_action.type != expected_action:
        raise PlanningValidationError("Planning status and next action are inconsistent.")

    normalized_candidates = deduplicate_portal_candidates(plan.portal_candidates)
    if len(normalized_candidates) != len(plan.portal_candidates):
        raise PlanningValidationError("Portal candidates must be safe and deduplicated.")

    normalized_fields = deduplicate_available_fields(plan.available_fields)
    if len(normalized_fields) != len(plan.available_fields):
        raise PlanningValidationError("Available fields must be non-empty and deduplicated.")

    action = plan.required_next_action
    if action.type == ActionType.OPEN_URL:
        target_key = equivalent_url_key(action.target or "")
        candidate_keys = {
            equivalent_url_key(candidate.url) for candidate in plan.portal_candidates
        }
        if target_key is None or target_key not in candidate_keys:
            raise PlanningValidationError(
                "OPEN_URL target must be a safe selected portal candidate."
            )
    elif action.type == ActionType.SEARCH_WEB:
        validate_search_query(action.query or "", sensitive_values(result))

    needs_input = plan.status == PlanningStatus.USER_INPUT_REQUIRED
    if plan.user_input_requirement.required != needs_input:
        raise PlanningValidationError(
            "User input requirement and planning status are inconsistent."
        )

    return plan
