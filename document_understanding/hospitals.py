"""Explicit hospital profiles; the general document engine remains the fallback."""

from dataclasses import dataclass
from enum import Enum
import re

from document_understanding.models import (
    ConfidenceLevel,
    DocumentUnderstandingResult,
    ExtractedField,
    FieldSemanticType,
)
from document_understanding.prompts import DOCUMENT_ANALYSIS_PROMPT


class Hospital(str, Enum):
    NORTHWEST = "northwest"
    RMI = "rmi"
    OTHER = "other"


@dataclass(frozen=True)
class HospitalProfile:
    label: str
    organization_pattern: str
    portal_url: str
    override_hosts: tuple[str, ...]
    field_labels: tuple[str, str]
    field_patterns: tuple[str, str]
    identifier_type: FieldSemanticType


PROFILES = {
    Hospital.NORTHWEST: HospitalProfile(
        label="Northwest",
        organization_pattern=r"\b(?:north\s*west|nwgh)\b",
        portal_url="https://reports.nwgh.pk/",
        override_hosts=("reports.nwgh.pk", "nwgh.pk", "www.nwgh.pk"),
        field_labels=("Invoice No.", "Access Code"),
        field_patterns=(
            r"^\s*(?:invoice|inv)\s*(?:no\.?|number|#|id)?\s*[:#.-]?\s*$",
            r"\baccess\s*code\b",
        ),
        identifier_type=FieldSemanticType.REFERENCE_IDENTIFIER,
    ),
    Hospital.RMI: HospitalProfile(
        label="RMI",
        organization_pattern=r"\b(?:rmi|rehman\s+medical\s+institute)\b",
        portal_url="https://labreports.rmi.edu.pk/",
        override_hosts=("labreports.rmi.edu.pk", "rmi.edu.pk"),
        field_labels=("Username", "Password"),
        field_patterns=(
            r"\b(?:user\s*(?:name|id)|login\s*(?:name|id))\b",
            r"\bpassword\b",
        ),
        identifier_type=FieldSemanticType.PATIENT_IDENTIFIER,
    ),
}

HOSPITAL_LABELS = {
    Hospital.NORTHWEST: "Northwest report",
    Hospital.RMI: "RMI report",
    Hospital.OTHER: "Other hospital",
}
HOSPITAL_HINTS = {
    Hospital.NORTHWEST: "Include the Invoice No. and Access Code in your photo.",
    Hospital.RMI: "Include the Username and Password printed on your receipt.",
    Hospital.OTHER: "Include the hospital name, report website or QR code, and access details.",
}


def analysis_prompt(hospital: Hospital = Hospital.OTHER) -> str:
    profile = PROFILES.get(hospital)
    if profile is None:
        return DOCUMENT_ANALYSIS_PROMPT
    first, second = profile.field_labels
    return (
        DOCUMENT_ANALYSIS_PROMPT
        + f"\n\nThe user selected {profile.label}. Treat this as a hint, not proof of "
        "the organization. Read the actual organization header so a wrong selection "
        f"can be detected. Prioritize the explicitly labeled {first} and {second} "
        "used for online reports. Return each as a separate field with its exact "
        "visible label and value. Do not substitute a patient, MR, sample, receipt, "
        "or order number for the requested login identifier. Leave missing or "
        "unreadable fields absent; never guess them."
    )


def focused_document(
    document: DocumentUnderstandingResult, hospital: Hospital
) -> DocumentUnderstandingResult:
    """Restrict focused retrieval to one unambiguous value per required label."""
    profile = PROFILES.get(hospital)
    if profile is None:
        return document
    fields: list[ExtractedField] = []
    for pattern, semantic_type in zip(
        profile.field_patterns,
        (profile.identifier_type, FieldSemanticType.ACCESS_CREDENTIAL),
    ):
        candidates = [
            field
            for field in document.fields
            if re.search(pattern, field.label or "", re.I)
            and sum(
                bool(re.search(role, field.label or "", re.I))
                for role in profile.field_patterns
            )
            == 1
            and field.value.strip()
            and field.confidence in {ConfidenceLevel.HIGH, ConfidenceLevel.MEDIUM}
        ]
        # Disagreeing reads must never select an arbitrary credential.
        if len({field.value for field in candidates}) != 1:
            continue
        best = next(
            (field for field in candidates if field.confidence == ConfidenceLevel.HIGH),
            candidates[0],
        )
        fields.append(best.model_copy(update={"semantic_type": semantic_type}))
    return document.model_copy(update={"fields": fields, "dates": []})


def profile_requirement(
    document: DocumentUnderstandingResult, hospital: Hospital
) -> tuple[str, list[str]] | None:
    profile = PROFILES[hospital]
    organization = document.organization
    if (
        organization
        and organization.name
        and organization.name.casefold() != "unknown"
        and organization.confidence in {ConfidenceLevel.HIGH, ConfidenceLevel.MEDIUM}
        and not re.search(profile.organization_pattern, organization.name, re.I)
    ):
        return (
            f"This slip does not appear to be from {profile.label}. "
            "Select the correct hospital or Other hospital and scan again.",
            ["Correct hospital selection"],
        )
    missing = [
        label
        for label, pattern in zip(profile.field_labels, profile.field_patterns)
        if not any(
            re.search(pattern, field.label or "", re.I) for field in document.fields
        )
    ]
    if missing:
        return (
            "Take a clearer photo showing " + " and ".join(missing) + ".",
            missing,
        )
    return None
