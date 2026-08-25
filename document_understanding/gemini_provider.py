"""Gemini multimodal provider through Google's OpenAI-compatible endpoint."""

import base64
from collections.abc import Callable, Mapping
from pathlib import Path
from time import sleep
from typing import Any, TypeVar

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    OpenAI,
    RateLimitError,
)

from document_understanding.credential_focus import (
    CREDENTIAL_FOCUS_PROMPT,
    CredentialFocusResult,
    focused_fields_from_payload,
    merge_credential_fields,
    needs_credential_focus,
    normalize_explicit_credentials,
)
from document_understanding.models import DocumentUnderstandingResult
from document_understanding.parser import (
    DocumentParseError,
    parse_document_json,
    parse_document_result,
)
from document_understanding.prompts import DOCUMENT_ANALYSIS_PROMPT
from document_understanding.provider import (
    ProviderConfigurationError,
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from utils.logger import get_logger


logger = get_logger(__name__)
MIME_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}
PARSE_FALLBACK_STATUS_CODES = {400, 404, 405, 415, 422, 501}
TRANSIENT_RETRY_SECONDS = 1.0
ALLOWED_REASONING_EFFORTS = {"none", "minimal", "low", "medium", "high"}
ResultT = TypeVar("ResultT")


class GeminiDocumentVisionProvider:
    """Return the shared document schema without exposing Gemini to callers."""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float,
        reasoning_effort: str,
        credential_focus_timeout_seconds: float = 12.0,
    ) -> None:
        self._model = model
        self._credential_focus_timeout_seconds = max(
            1.0,
            min(timeout_seconds, credential_focus_timeout_seconds),
        )
        self._reasoning_effort = reasoning_effort.strip().lower()
        if self._reasoning_effort not in ALLOWED_REASONING_EFFORTS:
            raise ProviderConfigurationError(
                "GEMINI_REASONING_EFFORT must be none, minimal, low, medium, or high."
            )
        self._client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout_seconds,
            max_retries=0,
        )

    def analyze_document(self, image_path: Path) -> DocumentUnderstandingResult:
        image_url = self._image_data_url(image_path)
        messages = self._messages(image_url)
        try:
            parsed = self._parse_structured(messages)
        except (AttributeError, NotImplementedError, TypeError):
            logger.info("Gemini structured parse is unavailable; using JSON schema fallback")
            result = self._create_structured_fallback(messages)
            return self._finalize_result(image_url, result)
        except APIStatusError as exc:
            if exc.status_code in PARSE_FALLBACK_STATUS_CODES:
                logger.info(
                    "Gemini structured parse was rejected; using JSON schema fallback"
                )
                result = self._create_structured_fallback(messages)
                return self._finalize_result(image_url, result)
            self._raise_provider_error(exc)
        except Exception as exc:
            self._raise_provider_error(exc)

        if parsed is None:
            logger.info("Gemini structured parse was empty; using JSON schema fallback")
            result = self._create_structured_fallback(messages)
            return self._finalize_result(image_url, result)
        result = self._validate_parsed(parsed)
        return self._finalize_result(image_url, result)

    @staticmethod
    def _image_data_url(image_path: Path) -> str:
        mime_type = MIME_TYPES.get(image_path.suffix.lower())
        if mime_type is None:
            raise ProviderResponseError("Unsupported temporary image format.")
        if not image_path.is_file():
            raise ProviderResponseError("Temporary document image is unavailable.")
        try:
            encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
        except OSError as exc:
            raise ProviderResponseError(
                "Temporary document image could not be read."
            ) from exc
        return f"data:{mime_type};base64,{encoded}"

    @staticmethod
    def _messages(image_url: str) -> list[dict[str, Any]]:
        return [
            {"role": "system", "content": DOCUMENT_ANALYSIS_PROMPT},
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "Analyze this document image using the required schema.",
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": image_url},
                    },
                ],
            },
        ]

    def _parse_structured(
        self, messages: list[dict[str, Any]]
    ) -> object | None:
        completion = self._request_with_transient_retry(
            lambda: self._client.beta.chat.completions.parse(
                model=self._model,
                messages=messages,
                response_format=DocumentUnderstandingResult,
                reasoning_effort=self._reasoning_effort,
            )
        )
        if not completion.choices:
            return None
        return completion.choices[0].message.parsed

    def _create_structured_fallback(
        self, messages: list[dict[str, Any]]
    ) -> DocumentUnderstandingResult:
        try:
            completion = self._request_with_transient_retry(
                lambda: self._client.chat.completions.create(
                    model=self._model,
                    messages=messages,
                    reasoning_effort=self._reasoning_effort,
                    response_format={
                        "type": "json_schema",
                        "json_schema": {
                            "name": "document_understanding_result",
                            "strict": True,
                            "schema": DocumentUnderstandingResult.model_json_schema(),
                        },
                    },
                )
            )
        except Exception as exc:
            self._raise_provider_error(exc)

        if not completion.choices:
            raise ProviderResponseError(
                "Gemini returned no structured document result."
            )
        content = completion.choices[0].message.content
        if not isinstance(content, str) or not content.strip():
            raise ProviderResponseError(
                "Gemini returned no structured document result."
            )
        try:
            return parse_document_json(content)
        except DocumentParseError as exc:
            raise ProviderResponseError(
                "Gemini returned invalid structured document data."
            ) from exc

    def _finalize_result(
        self,
        image_url: str,
        result: DocumentUnderstandingResult,
    ) -> DocumentUnderstandingResult:
        normalized = normalize_explicit_credentials(result)
        if not needs_credential_focus(normalized):
            return normalized
        return self._supplement_credentials(image_url, normalized)

    def _supplement_credentials(
        self,
        image_url: str,
        result: DocumentUnderstandingResult,
    ) -> DocumentUnderstandingResult:
        messages = [
            {"role": "system", "content": CREDENTIAL_FOCUS_PROMPT},
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "Read only the explicitly labeled report-login fields.",
                    },
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            },
        ]
        try:
            completion = self._request_with_transient_retry(
                lambda: self._client.beta.chat.completions.parse(
                    model=self._model,
                    messages=messages,
                    response_format=CredentialFocusResult,
                    reasoning_effort=self._reasoning_effort,
                    timeout=self._credential_focus_timeout_seconds,
                )
            )
            if not completion.choices:
                return result
            parsed = completion.choices[0].message.parsed
            additions = focused_fields_from_payload(parsed)
        except Exception as exc:
            logger.warning(
                "Focused credential extraction was unavailable: %s",
                type(exc).__name__,
            )
            return result

        if not additions:
            return result
        merged = merge_credential_fields(result.fields, additions)
        logger.info("Focused report-access field check completed")
        return result.model_copy(update={"fields": merged})

    @staticmethod
    def _request_with_transient_retry(operation: Callable[[], ResultT]) -> ResultT:
        for attempt in range(2):
            try:
                return operation()
            except APITimeoutError:
                # A full request timeout has already consumed the latency budget.
                # Retrying it would double the user's wait without a quick signal
                # that the service has recovered.
                raise
            except (APIConnectionError, APIStatusError, RateLimitError) as exc:
                transient = (
                    isinstance(exc, (APIConnectionError, RateLimitError))
                    or isinstance(exc, APIStatusError)
                    and exc.status_code >= 500
                )
                if not transient or attempt == 1:
                    raise
                logger.info("Gemini request was transiently unavailable; retrying once")
                sleep(TRANSIENT_RETRY_SECONDS)
        raise RuntimeError("Unreachable Gemini retry state.")

    @staticmethod
    def _validate_parsed(parsed: object) -> DocumentUnderstandingResult:
        if isinstance(parsed, DocumentUnderstandingResult):
            payload: Mapping[str, Any] = parsed.model_dump(mode="json")
        elif isinstance(parsed, Mapping):
            payload = parsed
        elif hasattr(parsed, "model_dump"):
            dumped = parsed.model_dump(mode="json")
            if not isinstance(dumped, Mapping):
                raise ProviderResponseError(
                    "Gemini returned invalid structured document data."
                )
            payload = dumped
        else:
            raise ProviderResponseError(
                "Gemini returned invalid structured document data."
            )
        try:
            return parse_document_result(payload)
        except DocumentParseError as exc:
            raise ProviderResponseError(
                "Gemini returned invalid structured document data."
            ) from exc

    @staticmethod
    def _raise_provider_error(exc: Exception) -> None:
        if isinstance(exc, AuthenticationError):
            logger.warning("Gemini document provider authentication failed")
            raise ProviderConfigurationError(
                "Gemini document provider authentication failed."
            ) from exc
        if isinstance(exc, APITimeoutError):
            logger.warning("Gemini document provider timed out")
            raise ProviderTimeoutError(
                "Gemini document provider timed out."
            ) from exc
        if isinstance(exc, RateLimitError):
            logger.warning("Gemini document provider rate limit reached")
            raise ProviderUnavailableError(
                "Gemini document provider is temporarily unavailable."
            ) from exc
        if isinstance(exc, APIConnectionError):
            logger.warning("Gemini document provider connection failed")
            raise ProviderUnavailableError(
                "Gemini document provider is temporarily unavailable."
            ) from exc
        if isinstance(exc, APIStatusError):
            if exc.status_code in {401, 403}:
                logger.warning("Gemini document provider authentication failed")
                raise ProviderConfigurationError(
                    "Gemini document provider authentication failed."
                ) from exc
            if exc.status_code in {408, 504}:
                logger.warning("Gemini document provider timed out")
                raise ProviderTimeoutError(
                    "Gemini document provider timed out."
                ) from exc
            if exc.status_code == 429 or exc.status_code >= 500:
                logger.warning("Gemini document provider is temporarily unavailable")
                raise ProviderUnavailableError(
                    "Gemini document provider is temporarily unavailable."
                ) from exc
            logger.warning("Gemini document provider returned an API error")
            raise ProviderResponseError(
                "Gemini document provider returned an API error."
            ) from exc
        logger.warning("Unexpected Gemini document provider error: %s", type(exc).__name__)
        raise ProviderResponseError(
            "Gemini document provider could not analyze the image."
        ) from exc
