"""Post-provider validation and safe normalization."""

from urllib.parse import urlparse

from document_understanding.models import (
    DocumentUnderstandingResult,
    ExtractedDate,
    ExtractedField,
    ExtractedURL,
    QRCodeResult,
)


def normalize_http_url(value: str) -> str | None:
    candidate = value.strip()
    if candidate.lower().startswith("www."):
        candidate = f"https://{candidate}"
    elif "://" not in candidate:
        possible_host = candidate.split("/", 1)[0]
        if "." in possible_host and not any(char.isspace() for char in candidate):
            candidate = f"https://{candidate}"
    parsed = urlparse(candidate)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return None
    return candidate


def _dedupe_fields(fields: list[ExtractedField]) -> list[ExtractedField]:
    output: list[ExtractedField] = []
    seen: set[tuple[str, str, str]] = set()
    for field in fields:
        if not field.value.strip():
            continue
        key = (
            (field.label or "").strip().casefold(),
            field.value.strip().casefold(),
            field.semantic_type.value,
        )
        if key not in seen:
            seen.add(key)
            output.append(field)
    return output


def _dedupe_dates(dates: list[ExtractedDate]) -> list[ExtractedDate]:
    output: list[ExtractedDate] = []
    seen: set[tuple[str, str, str]] = set()
    for item in dates:
        if not item.value.strip():
            continue
        key = (
            (item.label or "").strip().casefold(),
            item.value.strip().casefold(),
            item.semantic_type.value,
        )
        if key not in seen:
            seen.add(key)
            output.append(item)
    return output


def _normalize_urls(
    urls: list[ExtractedURL], warnings: list[str]
) -> tuple[list[ExtractedURL], list[str]]:
    output: list[ExtractedURL] = []
    seen: set[str] = set()
    for item in urls:
        if not item.url.strip():
            continue
        normalized = normalize_http_url(item.normalized_url or item.url)
        if normalized is None:
            warnings.append("A possible URL was omitted because its syntax was invalid.")
            continue
        key = normalized.casefold().rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        output.append(item.model_copy(update={"normalized_url": normalized}))
    return output, warnings


def _dedupe_qr_codes(codes: list[QRCodeResult]) -> list[QRCodeResult]:
    output: list[QRCodeResult] = []
    seen: set[str] = set()
    for code in codes:
        value = code.value.strip()
        if not value or value.casefold() in seen:
            continue
        seen.add(value.casefold())
        output.append(code)
    return output


def _dedupe_text(values: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        clean = value.strip()
        if clean and clean.casefold() not in seen:
            seen.add(clean.casefold())
            output.append(clean)
    return output


def normalize_result(result: DocumentUnderstandingResult) -> DocumentUnderstandingResult:
    warnings = _dedupe_text(result.warnings)
    urls, warnings = _normalize_urls(result.urls, warnings)
    return result.model_copy(
        update={
            "document_type": result.document_type.strip() or "unknown",
            "purpose": result.purpose.strip() or "unknown",
            "likely_action": result.likely_action.strip() or "unknown",
            "raw_summary": result.raw_summary.strip(),
            "fields": _dedupe_fields(result.fields),
            "dates": _dedupe_dates(result.dates),
            "urls": urls,
            "qr_codes": _dedupe_qr_codes(result.qr_codes),
            "instructions": _dedupe_text(result.instructions),
            "warnings": _dedupe_text(warnings),
        }
    )


def merge_qr_codes(
    result: DocumentUnderstandingResult,
    decoded_codes: list[QRCodeResult],
    decoder_warnings: list[str],
) -> DocumentUnderstandingResult:
    return normalize_result(
        result.model_copy(
            update={
                "qr_codes": [*result.qr_codes, *decoded_codes],
                "warnings": [*result.warnings, *decoder_warnings],
            }
        )
    )
