"""OpenAI multimodal provider implementation."""

import base64
from pathlib import Path

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    OpenAI,
    RateLimitError,
)

from document_understanding.models import DocumentUnderstandingResult
from document_understanding.parser import DocumentParseError, parse_document_result
from document_understanding.prompts import DOCUMENT_ANALYSIS_PROMPT
from document_understanding.provider import (
    ProviderConfigurationError,
    ProviderResponseError,
    ProviderUnavailableError,
)
from utils.logger import get_logger


logger = get_logger(__name__)
MIME_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}


class OpenAIDocumentVisionProvider:
    def __init__(self, api_key: str, model: str, timeout_seconds: float) -> None:
        self._model = model
        self._client = OpenAI(api_key=api_key, timeout=timeout_seconds)

    def analyze_document(self, image_path: Path) -> DocumentUnderstandingResult:
        mime_type = MIME_TYPES.get(image_path.suffix.lower())
        if mime_type is None:
            raise ProviderResponseError("Unsupported temporary image format.")

        encoded_image = base64.b64encode(image_path.read_bytes()).decode("ascii")
        image_url = f"data:{mime_type};base64,{encoded_image}"

        try:
            response = self._client.responses.parse(
                model=self._model,
                instructions=DOCUMENT_ANALYSIS_PROMPT,
                input=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": "Analyze this document image using the required schema.",
                            },
                            {
                                "type": "input_image",
                                "image_url": image_url,
                                "detail": "high",
                            },
                        ],
                    }
                ],
                text_format=DocumentUnderstandingResult,
                store=False,
            )
        except AuthenticationError as exc:
            logger.warning("Document provider authentication failed")
            raise ProviderConfigurationError("Document provider authentication failed.") from exc
        except (RateLimitError, APIConnectionError, APITimeoutError) as exc:
            logger.warning("Document provider temporarily unavailable: %s", type(exc).__name__)
            raise ProviderUnavailableError("Document provider is temporarily unavailable.") from exc
        except APIStatusError as exc:
            logger.warning("Document provider returned an API error: %s", type(exc).__name__)
            raise ProviderResponseError("Document provider returned an API error.") from exc
        except Exception as exc:
            logger.warning("Unexpected document provider error: %s", type(exc).__name__)
            raise ProviderResponseError("Document provider could not analyze the image.") from exc

        parsed = response.output_parsed
        if parsed is None:
            raise ProviderResponseError("Document provider returned no structured result.")
        try:
            return parse_document_result(parsed.model_dump(mode="json"))
        except DocumentParseError as exc:
            raise ProviderResponseError("Document provider returned invalid structured data.") from exc
