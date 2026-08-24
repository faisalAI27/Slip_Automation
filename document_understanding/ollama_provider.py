"""Local Ollama vision provider implementation."""

import json
from pathlib import Path
import re

import httpx
from ollama import Client, RequestError, ResponseError

from document_understanding.models import (
    ConfidenceLevel,
    DocumentUnderstandingResult,
    ExtractedField,
    FieldSemanticType,
    URLPurpose,
)
from document_understanding.parser import DocumentParseError, parse_document_json
from document_understanding.prompts import DOCUMENT_ANALYSIS_PROMPT
from document_understanding.provider import (
    ProviderConfigurationError,
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from utils.logger import get_logger


logger = get_logger(__name__)
SUPPORTED_SUFFIXES = {".jpg", ".jpeg", ".png"}
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
    "its value exactly. Do not return patient, order, laboratory, sample, receipt, or "
    "invoice identifiers unless the visible label explicitly identifies a login field."
)


def _credential_role(field: ExtractedField) -> str | None:
    """Return a narrow authentication role without treating every ID as a login."""
    label = field.label or ""
    if SECRET_LABEL_PATTERN.search(label) or (
        field.semantic_type == FieldSemanticType.ACCESS_CREDENTIAL
    ):
        return "access_secret"
    if LOGIN_LABEL_PATTERN.search(label):
        return "login_identifier"
    return None


def _merge_credential_fields(
    existing: list[ExtractedField],
    focused: list[ExtractedField],
) -> list[ExtractedField]:
    """Keep one strongest field for each explicit report-login role.

    General and focused vision passes often transcribe the same printed label with
    slightly different wording. Treating those variations as separate credentials
    makes an otherwise deterministic website match appear ambiguous.
    """
    merged = list(existing)
    for candidate in focused:
        role = _credential_role(candidate)
        if role is None:
            continue
        matching_indexes = [
            index
            for index, item in enumerate(merged)
            if _credential_role(item) == role
        ]
        if not matching_indexes:
            merged.append(candidate)
            continue

        confidence_rank = {
            ConfidenceLevel.HIGH: 3,
            ConfidenceLevel.MEDIUM: 2,
            ConfidenceLevel.LOW: 1,
            ConfidenceLevel.UNKNOWN: 0,
        }
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


class OllamaDocumentVisionProvider:
    def __init__(self, base_url: str, model: str, timeout_seconds: float) -> None:
        self._model = model
        self._client = Client(host=base_url, timeout=timeout_seconds)

    def analyze_document(self, image_path: Path) -> DocumentUnderstandingResult:
        if image_path.suffix.lower() not in SUPPORTED_SUFFIXES:
            raise ProviderResponseError("Unsupported temporary image format.")
        if not image_path.is_file():
            raise ProviderResponseError("Temporary document image is unavailable.")

        schema = DocumentUnderstandingResult.model_json_schema()
        prompt = (
            f"{DOCUMENT_ANALYSIS_PROMPT}\n\n"
            "Return one concise JSON object matching the supplied response schema. "
            "Use empty arrays for categories with no visible evidence."
        )

        try:
            response = self._client.chat(
                model=self._model,
                messages=[
                    {
                        "role": "user",
                        "content": prompt,
                        "images": [str(image_path)],
                    }
                ],
                format=schema,
                think=False,
                options={
                    "temperature": 0,
                    "num_ctx": 6144,
                    "num_predict": 2048,
                },
                stream=False,
            )
        except httpx.TimeoutException as exc:
            logger.warning("Local document provider timed out")
            raise ProviderTimeoutError(
                "Ollama did not finish the document analysis before the timeout."
            ) from exc
        except ConnectionError as exc:
            logger.warning("Local document provider is unavailable")
            raise ProviderUnavailableError(
                "Ollama is not running or cannot be reached."
            ) from exc
        except RequestError as exc:
            logger.warning("Local document provider request was invalid")
            raise ProviderResponseError(
                "Ollama could not accept the document analysis request."
            ) from exc
        except ResponseError as exc:
            if exc.status_code == 404:
                logger.warning("Configured local document model is unavailable")
                raise ProviderConfigurationError(
                    "The configured Ollama model is not installed."
                ) from exc
            if exc.status_code >= 500:
                logger.warning("Local document provider returned a server error")
                raise ProviderUnavailableError(
                    "Ollama is temporarily unable to process the document."
                ) from exc
            logger.warning("Local document provider rejected the analysis request")
            raise ProviderResponseError(
                "Ollama could not analyze the document."
            ) from exc
        except Exception as exc:
            logger.warning("Unexpected local provider error: %s", type(exc).__name__)
            raise ProviderResponseError(
                "The local document provider could not analyze the image."
            ) from exc

        content = response.message.content
        if not content:
            raise ProviderResponseError("The local document provider returned no result.")
        try:
            result = parse_document_json(content)
        except DocumentParseError as exc:
            raise ProviderResponseError(
                "The local document provider returned invalid structured data."
            ) from exc
        result = self._normalize_explicit_credentials(result)
        if self._needs_credential_focus(result):
            result = self._supplement_credentials(image_path, result)
        return result

    @staticmethod
    def _normalize_explicit_credentials(
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

    @staticmethod
    def _needs_credential_focus(result: DocumentUnderstandingResult) -> bool:
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

    def _supplement_credentials(
        self,
        image_path: Path,
        result: DocumentUnderstandingResult,
    ) -> DocumentUnderstandingResult:
        try:
            response = self._client.chat(
                model=self._model,
                messages=[
                    {
                        "role": "user",
                        "content": CREDENTIAL_FOCUS_PROMPT,
                        "images": [str(image_path)],
                    }
                ],
                format=CREDENTIAL_FOCUS_SCHEMA,
                think=False,
                options={
                    "temperature": 0,
                    "num_ctx": 4096,
                    "num_predict": 512,
                },
                stream=False,
            )
            payload = json.loads(response.message.content or "")
            raw_fields = payload.get("fields", []) if isinstance(payload, dict) else []
            additions: list[ExtractedField] = []
            for raw in raw_fields:
                if not isinstance(raw, dict):
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
        except Exception as exc:
            logger.warning(
                "Focused credential extraction was unavailable: %s",
                type(exc).__name__,
            )
            return result

        merged = _merge_credential_fields(result.fields, additions)
        logger.info("Focused report-access field check completed")
        return result.model_copy(update={"fields": merged})
