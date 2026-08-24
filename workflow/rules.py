"""Deterministic, organization-agnostic Phase 3 planning rules."""

import re
from urllib.parse import urlsplit

from document_understanding.models import (
    ConfidenceLevel,
    DocumentUnderstandingResult,
    FieldSemanticType,
    OrganizationType,
    QRContentType,
    URLPurpose,
)
from workflow.models import (
    AvailableField,
    InformationSource,
    PlannedOrganization,
    PortalCandidate,
    PortalSource,
    PotentialUse,
)
from workflow.validation import (
    deduplicate_available_fields,
    deduplicate_portal_candidates,
    normalize_navigation_url,
)


REASONABLE_CONFIDENCE = {ConfidenceLevel.HIGH, ConfidenceLevel.MEDIUM}
REPORT_URL_HINTS = {
    "lab",
    "laboratory",
    "patient",
    "portal",
    "report",
    "reports",
    "result",
    "results",
}

IDENTIFIER_TYPES = {
    FieldSemanticType.PATIENT_IDENTIFIER,
    FieldSemanticType.REGISTRATION_IDENTIFIER,
    FieldSemanticType.VISIT_IDENTIFIER,
    FieldSemanticType.REFERENCE_IDENTIFIER,
    FieldSemanticType.SAMPLE_IDENTIFIER,
    FieldSemanticType.REPORT_IDENTIFIER,
    FieldSemanticType.ORGANIZATION_IDENTIFIER,
    FieldSemanticType.PERSON_NAME,
}


def known_organization(result: DocumentUnderstandingResult) -> PlannedOrganization | None:
    organization = result.organization
    if not organization or not organization.name:
        return None
    name = organization.name.strip()
    if not name or name.casefold() == "unknown":
        return None
    return PlannedOrganization(
        name=name,
        type=organization.type,
        confidence=organization.confidence,
    )


def _field_use(semantic_type: FieldSemanticType) -> PotentialUse:
    if semantic_type == FieldSemanticType.ACCESS_CREDENTIAL:
        return PotentialUse.PORTAL_AUTHENTICATION
    if semantic_type in IDENTIFIER_TYPES:
        return PotentialUse.PORTAL_FORM_INPUT
    if semantic_type in {FieldSemanticType.PHONE_NUMBER, FieldSemanticType.EMAIL}:
        return PotentialUse.CONTACT_INFORMATION
    if semantic_type == FieldSemanticType.DATE:
        return PotentialUse.REFERENCE_INFORMATION
    return PotentialUse.CONTEXT_ONLY


def build_available_fields(result: DocumentUnderstandingResult) -> list[AvailableField]:
    fields = [
        AvailableField(
            label=item.label,
            value=item.value,
            semantic_type=item.semantic_type,
            source=InformationSource.DOCUMENT_FIELD,
            potential_use=_field_use(item.semantic_type),
            confidence=item.confidence,
        )
        for item in result.fields
        if item.value.strip()
    ]
    fields.extend(
        AvailableField(
            label=item.label,
            value=item.value,
            semantic_type=item.semantic_type,
            source=InformationSource.DOCUMENT_DATE,
            potential_use=PotentialUse.REFERENCE_INFORMATION,
            confidence=item.confidence,
        )
        for item in result.dates
        if item.value.strip()
    )
    return deduplicate_available_fields(fields)


def _looks_like_report_url(value: str) -> bool:
    normalized = normalize_navigation_url(value)
    if normalized is None:
        return False
    parsed = urlsplit(normalized)
    public_location = f"{parsed.hostname or ''} {parsed.path}".casefold()
    tokens = {token for token in re.split(r"[^a-z0-9]+", public_location) if token}
    return bool(tokens & REPORT_URL_HINTS) or any(
        hint in public_location for hint in ("/report", "/result", "/patient", "/portal")
    )


def build_portal_candidates(
    result: DocumentUnderstandingResult,
) -> tuple[list[PortalCandidate], list[str]]:
    candidates: list[PortalCandidate] = []
    warnings: list[str] = []

    for item in result.urls:
        normalized = normalize_navigation_url(item.normalized_url or item.url)
        if normalized is None:
            warnings.append("A document URL was excluded because it is not a safe HTTP(S) URL.")
            continue
        if item.confidence not in REASONABLE_CONFIDENCE:
            warnings.append("A low-confidence document URL was not selected for navigation.")
            continue
        if item.likely_purpose == URLPurpose.REPORT_PORTAL:
            candidates.append(
                PortalCandidate(
                    url=normalized,
                    source=PortalSource.PRINTED_URL,
                    likely_purpose=URLPurpose.REPORT_PORTAL,
                    confidence=item.confidence,
                    reason="The document identifies this as a likely report portal.",
                )
            )
        elif item.likely_purpose == URLPurpose.ORGANIZATION_HOMEPAGE:
            candidates.append(
                PortalCandidate(
                    url=normalized,
                    source=PortalSource.ORGANIZATION_HOMEPAGE,
                    likely_purpose=URLPurpose.ORGANIZATION_HOMEPAGE,
                    confidence=item.confidence,
                    reason="The document identifies this as the organization homepage.",
                )
            )

    for item in result.qr_codes:
        if item.type != QRContentType.URL:
            continue
        normalized = normalize_navigation_url(item.value)
        if normalized is None:
            warnings.append("A QR URL was excluded because it is not a safe HTTP(S) URL.")
            continue
        if item.confidence not in REASONABLE_CONFIDENCE or not _looks_like_report_url(
            normalized
        ):
            warnings.append("A QR URL was not selected because report relevance is uncertain.")
            continue
        candidates.append(
            PortalCandidate(
                url=normalized,
                source=PortalSource.QR_CODE,
                likely_purpose=URLPurpose.REPORT_PORTAL,
                confidence=item.confidence,
                reason="The QR code contains a safe URL that appears related to report access.",
            )
        )

    return deduplicate_portal_candidates(candidates), list(dict.fromkeys(warnings))


def select_portal_candidate(
    candidates: list[PortalCandidate],
) -> PortalCandidate | None:
    source_priority = {
        PortalSource.PRINTED_URL: 0,
        PortalSource.QR_CODE: 1,
        PortalSource.ORGANIZATION_HOMEPAGE: 2,
        PortalSource.USER_PROVIDED_URL: 3,
        PortalSource.FUTURE_WEB_SEARCH: 4,
    }
    confidence_priority = {
        ConfidenceLevel.HIGH: 0,
        ConfidenceLevel.MEDIUM: 1,
        ConfidenceLevel.LOW: 2,
        ConfidenceLevel.UNKNOWN: 3,
    }
    return min(
        candidates,
        key=lambda item: (source_priority[item.source], confidence_priority[item.confidence]),
        default=None,
    )


def safe_search_query(organization: PlannedOrganization) -> str:
    return f"{organization.name} online report portal"


def has_low_confidence_context(result: DocumentUnderstandingResult) -> bool:
    return result.overall_confidence in {ConfidenceLevel.LOW, ConfidenceLevel.UNKNOWN} or (
        result.organization is not None
        and (
            result.organization.type == OrganizationType.UNKNOWN
            or result.organization.confidence
            in {ConfidenceLevel.LOW, ConfidenceLevel.UNKNOWN}
        )
    )
