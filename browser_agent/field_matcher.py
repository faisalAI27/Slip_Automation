"""Organization-independent semantic mapping from document fields to page inputs."""

from dataclasses import dataclass
import re

from browser_agent.models import (
    FieldMappingResult,
    FieldMatch,
    HtmlInputType,
    InputFieldObservation,
    SafeDocumentField,
    UserProvidedField,
)
from document_understanding.models import ConfidenceLevel
from workflow.models import AvailableField


IDENTIFIER_CATEGORIES = {
    "patient_identifier",
    "registration_identifier",
    "visit_identifier",
    "reference_identifier",
    "sample_identifier",
    "report_identifier",
    "organization_identifier",
}
IGNORED_INPUT_TYPES = {
    HtmlInputType.CHECKBOX,
    HtmlInputType.RADIO,
    HtmlInputType.SELECT,
}


@dataclass(frozen=True, slots=True)
class StoredDocumentField:
    descriptor: SafeDocumentField
    value: str


class DocumentFieldStore:
    """Keep sensitive values behind opaque references."""

    def __init__(
        self,
        available_fields: list[AvailableField],
        user_fields: list[UserProvidedField] | None = None,
    ) -> None:
        supplied = user_fields or []
        supplied_labels = {
            " ".join(re.findall(r"[a-z0-9]+", item.label.casefold()))
            for item in supplied
        }
        values: list[tuple[str | None, str, str, ConfidenceLevel]] = [
            (item.label, item.value, item.semantic_type, ConfidenceLevel.HIGH)
            for item in supplied
        ]
        values.extend(
            (
                item.label,
                item.value,
                item.semantic_type.value,
                item.confidence,
            )
            for item in available_fields
            if " ".join(re.findall(r"[a-z0-9]+", (item.label or "").casefold()))
            not in supplied_labels
        )
        self._fields: dict[str, StoredDocumentField] = {}
        for index, (label, value, semantic_type, confidence) in enumerate(values, 1):
            ref = f"doc_field_{index}"
            self._fields[ref] = StoredDocumentField(
                descriptor=SafeDocumentField(
                    ref=ref,
                    label=label,
                    semantic_type=semantic_type,
                    confidence=confidence,
                ),
                value=value,
            )

    @property
    def descriptors(self) -> list[SafeDocumentField]:
        return [item.descriptor for item in self._fields.values()]

    def descriptor(self, ref: str) -> SafeDocumentField | None:
        item = self._fields.get(ref)
        return item.descriptor if item else None

    def resolve(self, ref: str) -> str:
        return self._fields[ref].value

    def contains(self, ref: str) -> bool:
        return ref in self._fields


def _tokens(value: str | None) -> set[str]:
    raw = re.findall(r"[a-z0-9]+", (value or "").casefold())
    normalized: set[str] = set()
    aliases = {
        "mrn": "patient",
        "mr": "patient",
        "medical": "patient",
        "record": "patient",
        "number": "id",
        "no": "id",
        "num": "id",
        "registration": "registration",
        "reg": "registration",
        "password": "credential",
        "passcode": "credential",
        "pin": "credential",
        "token": "credential",
        "secret": "credential",
        "online": "credential",
        "web": "credential",
        "code": "credential",
        "username": "patient",
        "userid": "patient",
        "user": "patient",
        "login": "patient",
        "dob": "birth",
        "birthday": "birth",
    }
    for token in raw:
        normalized.add(aliases.get(token, token))
    return normalized


def _page_category(field: InputFieldObservation) -> str:
    tokens = _tokens(
        " ".join(
            filter(None, (field.label, field.name, field.placeholder, field.aria_label))
        )
    )
    if field.html_type == HtmlInputType.PASSWORD or tokens & {
        "credential",
    }:
        return "access_credential"
    if "birth" in tokens:
        return "date_of_birth"
    if "email" in tokens:
        return "email"
    if tokens & {"phone", "mobile", "telephone"}:
        return "phone_number"
    if "sample" in tokens or "lab" in tokens:
        return "sample_identifier"
    if "report" in tokens or "result" in tokens:
        return "report_identifier"
    if "visit" in tokens or "encounter" in tokens:
        return "visit_identifier"
    if "reference" in tokens or "ref" in tokens:
        return "reference_identifier"
    if "registration" in tokens:
        return "registration_identifier"
    if tokens & {"patient", "id", "identifier"}:
        return "patient_identifier"
    if field.html_type == HtmlInputType.DATE or "date" in tokens:
        return "date"
    return "unknown"


def _document_category(field: SafeDocumentField) -> str:
    semantic = field.semantic_type
    label_tokens = _tokens(field.label)
    if "birth" in label_tokens:
        return "date_of_birth"
    if "patient" in label_tokens and "credential" not in label_tokens:
        return "patient_identifier"
    if semantic in IDENTIFIER_CATEGORIES:
        return semantic
    if semantic == "access_credential":
        return semantic
    if semantic in {"date", "registration_date", "collection_date", "report_date"}:
        return "date"
    return semantic


def _score(document: SafeDocumentField, page: InputFieldObservation) -> float:
    doc_category = _document_category(document)
    page_category = _page_category(page)
    doc_tokens = _tokens(document.label)
    page_tokens = _tokens(
        " ".join(
            filter(None, (page.label, page.name, page.placeholder, page.aria_label))
        )
    )
    score = 0.0
    if doc_category == page_category and doc_category != "unknown":
        score = 0.84
    elif doc_category in IDENTIFIER_CATEGORIES and page_category in IDENTIFIER_CATEGORIES:
        score = 0.79
    elif doc_category == "date" and page_category == "date":
        score = 0.72
    elif document.semantic_type == "unknown" and doc_tokens & page_tokens:
        score = 0.62

    if doc_tokens and page_tokens:
        overlap = len(doc_tokens & page_tokens) / len(doc_tokens | page_tokens)
        score += min(0.18, overlap * 0.3)
    if page.html_type == HtmlInputType.PASSWORD:
        score += 0.12 if doc_category == "access_credential" else -0.25
    if document.confidence in {ConfidenceLevel.LOW, ConfidenceLevel.UNKNOWN}:
        score -= 0.18
    return max(0.0, min(score, 1.0))


def _confidence(score: float) -> ConfidenceLevel:
    if score >= 0.78:
        return ConfidenceLevel.HIGH
    if score >= 0.62:
        return ConfidenceLevel.MEDIUM
    return ConfidenceLevel.LOW


def _page_label(field: InputFieldObservation) -> str:
    return (
        field.label
        or field.aria_label
        or field.placeholder
        or field.name
        or "Required website field"
    )


class FieldMatcher:
    def match(
        self,
        document_fields: list[SafeDocumentField],
        page_fields: list[InputFieldObservation],
    ) -> FieldMappingResult:
        usable_page_fields = [
            item
            for item in page_fields
            if not item.disabled
            and not item.readonly
            and item.html_type not in IGNORED_INPUT_TYPES
        ]
        matches: list[FieldMatch] = []
        unmatched: list[str] = []
        ambiguous: list[str] = []
        chosen_refs: dict[str, str] = {}

        for page in usable_page_fields:
            ranked = sorted(
                ((_score(document, page), document) for document in document_fields),
                key=lambda pair: pair[0],
                reverse=True,
            )
            if not ranked or ranked[0][0] < 0.62:
                if page.required:
                    unmatched.append(_page_label(page))
                continue
            best_score, best_document = ranked[0]
            if len(ranked) > 1 and ranked[1][0] >= 0.62 and (
                best_score - ranked[1][0]
            ) < 0.08:
                ambiguous.append(page.element_id)
                continue
            if best_document.ref in chosen_refs:
                ambiguous.extend(
                    [page.element_id, chosen_refs[best_document.ref]]
                )
                matches = [
                    item
                    for item in matches
                    if item.document_field_ref != best_document.ref
                ]
                continue
            chosen_refs[best_document.ref] = page.element_id
            matches.append(
                FieldMatch(
                    document_field_ref=best_document.ref,
                    document_label=best_document.label,
                    document_semantic_type=best_document.semantic_type,
                    input_element_id=page.element_id,
                    page_field_label=_page_label(page),
                    confidence=_confidence(best_score),
                )
            )

        return FieldMappingResult(
            matches=matches,
            unmatched_required_inputs=list(dict.fromkeys(unmatched)),
            ambiguous_input_references=list(dict.fromkeys(ambiguous)),
        )
