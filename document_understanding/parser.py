"""Convert provider payloads into validated domain objects."""

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from document_understanding.models import DocumentUnderstandingResult
from document_understanding.validation import normalize_result


class DocumentParseError(ValueError):
    """Raised when a provider returns unusable structured output."""


def parse_document_result(payload: Mapping[str, Any]) -> DocumentUnderstandingResult:
    try:
        result = DocumentUnderstandingResult.model_validate(payload)
    except (ValidationError, TypeError, ValueError) as exc:
        raise DocumentParseError("The provider returned malformed structured output.") from exc
    return normalize_result(result)


def parse_document_json(payload: str) -> DocumentUnderstandingResult:
    try:
        result = DocumentUnderstandingResult.model_validate_json(payload)
    except (ValidationError, TypeError, ValueError) as exc:
        raise DocumentParseError("The provider returned malformed structured output.") from exc
    return normalize_result(result)
