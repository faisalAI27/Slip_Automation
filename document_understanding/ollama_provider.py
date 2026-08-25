"""Local Ollama vision provider implementation."""

import json
from pathlib import Path

import httpx
from ollama import Client, RequestError, ResponseError

from document_understanding.credential_focus import (
    CREDENTIAL_FOCUS_PROMPT,
    CREDENTIAL_FOCUS_SCHEMA,
    focused_fields_from_payload,
    merge_credential_fields,
    needs_credential_focus,
    normalize_explicit_credentials,
)
from document_understanding.models import DocumentUnderstandingResult
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
        result = normalize_explicit_credentials(result)
        if needs_credential_focus(result):
            result = self._supplement_credentials(image_path, result)
        return result

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
            additions = focused_fields_from_payload(payload)
        except Exception as exc:
            logger.warning(
                "Focused credential extraction was unavailable: %s",
                type(exc).__name__,
            )
            return result

        merged = merge_credential_fields(result.fields, additions)
        logger.info("Focused report-access field check completed")
        return result.model_copy(update={"fields": merged})
