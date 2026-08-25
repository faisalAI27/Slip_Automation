"""Shared, provider-independent report credential normalization."""

from collections.abc import Mapping
import re

from document_understanding.models import (
    ConfidenceLevel,
    DocumentUnderstandingResult,
    ExtractedField,
    FieldSemanticType,
    StrictModel,
    URLPurpose,
)


LOGIN_LABEL_PATTERN = re.compile(
    r"\b(?:user\s*(?:id|name)|login\s*(?:id|name))\b",
    re.I,
)
SECRET_LABEL_PATTERN = re.compile(
    r"\b(?:password|passcode|pin|access\s*code)\b",
    re.I,
)
CREDENTIAL_FOCUS_SCHEMA = {
    "type": "object",
    "properties": {
        "fields": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "value": {"type": "string"},
                    "confidence": {
                        "type": "string",
                        "enum": ["high", "medium", "low"],
                    },
                },
                "required": ["label", "value", "confidence"],
            },
        }
    },
    "required": ["fields"],
}
CREDENTIAL_FOCUS_PROMPT = (
    "Inspect this medical document only for explicitly labeled online-report login "
    "fields: USER ID, USERNAME, LOGIN ID, PASSWORD, PASSCODE, PIN, or ACCESS CODE. "
    "Return each visible labeled login identifier or secret separately and preserve "
    "its value exactly, character by character. Do not return patient, order, "
    "laboratory, sample, receipt, or invoice identifiers unless the visible label "
    "explicitly identifies a login field."
)


class FocusedCredentialField(StrictModel):
    label: str
    value: str
    confidence: ConfidenceLevel


class CredentialFocusResult(StrictModel):
    fields: list[FocusedCredentialField]


def credential_role(field: ExtractedField) -> str | None:
    """Return a narrow authentication role without treating every ID as a login."""
    label = field.label or ""
    if SECRET_LABEL_PATTERN.search(label) or (
        field.semantic_type == FieldSemanticType.ACCESS_CREDENTIAL
    ):
        return "access_secret"
    if LOGIN_LABEL_PATTERN.search(label):
        return "login_identifier"
    return None


def normalize_explicit_credentials(
    result: DocumentUnderstandingResult,
) -> DocumentUnderstandingResult:
    normalized: list[ExtractedField] = []
    for field in result.fields:
        label = field.label or ""
        semantic_type = field.semantic_type
        if SECRET_LABEL_PATTERN.search(label):
            semantic_type = FieldSemanticType.ACCESS_CREDENTIAL
        elif LOGIN_LABEL_PATTERN.search(label):
            semantic_type = FieldSemanticType.PATIENT_IDENTIFIER
        normalized.append(field.model_copy(update={"semantic_type": semantic_type}))
    return result.model_copy(update={"fields": normalized})


def needs_credential_focus(result: DocumentUnderstandingResult) -> bool:
    if not any(
        item.likely_purpose == URLPurpose.REPORT_PORTAL for item in result.urls
    ):
        return False
    field_evidence = any(
        LOGIN_LABEL_PATTERN.search(item.label or "")
        or SECRET_LABEL_PATTERN.search(item.label or "")
        or item.semantic_type == FieldSemanticType.ACCESS_CREDENTIAL
        for item in result.fields
    )
    instruction_evidence = any(
        LOGIN_LABEL_PATTERN.search(item) or SECRET_LABEL_PATTERN.search(item)
        for item in result.instructions
    )
    return field_evidence or instruction_evidence


def focused_fields_from_payload(payload: object) -> list[ExtractedField]:
    if isinstance(payload, CredentialFocusResult):
        raw_fields: list[object] = [
            item.model_dump(mode="json") for item in payload.fields
        ]
    elif isinstance(payload, Mapping):
        raw = payload.get("fields", [])
        raw_fields = list(raw) if isinstance(raw, list) else []
    else:
        return []

    additions: list[ExtractedField] = []
    for raw in raw_fields:
        if not isinstance(raw, Mapping):
            continue
        label = raw.get("label")
        value = raw.get("value")
        if not isinstance(label, str) or not isinstance(value, str) or not value:
            continue
        if SECRET_LABEL_PATTERN.search(label):
            semantic_type = FieldSemanticType.ACCESS_CREDENTIAL
        elif LOGIN_LABEL_PATTERN.search(label):
            semantic_type = FieldSemanticType.PATIENT_IDENTIFIER
        else:
            continue
        try:
            confidence = ConfidenceLevel(str(raw.get("confidence")))
        except ValueError:
            confidence = ConfidenceLevel.UNKNOWN
        additions.append(
            ExtractedField(
                label=label,
                value=value,
                semantic_type=semantic_type,
                confidence=confidence,
            )
        )
    return additions


def merge_credential_fields(
    existing: list[ExtractedField],
    focused: list[ExtractedField],
) -> list[ExtractedField]:
    """Keep one strongest field for each explicit report-login role."""
    merged = list(existing)
    confidence_rank = {
        ConfidenceLevel.HIGH: 3,
        ConfidenceLevel.MEDIUM: 2,
        ConfidenceLevel.LOW: 1,
        ConfidenceLevel.UNKNOWN: 0,
    }
    for candidate in focused:
        role = credential_role(candidate)
        if role is None:
            continue
        matching_indexes = [
            index
            for index, item in enumerate(merged)
            if credential_role(item) == role
        ]
        if not matching_indexes:
            merged.append(candidate)
            continue

        strongest_index = max(
            matching_indexes,
            key=lambda index: confidence_rank[merged[index].confidence],
        )
        strongest = merged[strongest_index]
        if confidence_rank[candidate.confidence] >= confidence_rank[strongest.confidence]:
            strongest = candidate

        first_index = matching_indexes[0]
        merged[first_index] = strongest
        for index in reversed(matching_indexes[1:]):
            del merged[index]
    return merged
