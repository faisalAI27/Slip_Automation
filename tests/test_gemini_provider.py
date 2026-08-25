import base64
from dataclasses import replace
import json
import logging
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

import httpx
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    RateLimitError,
)
from PIL import Image

from config.settings import get_settings
from document_understanding.gemini_provider import GeminiDocumentVisionProvider
from document_understanding.models import DocumentUnderstandingResult
from document_understanding.ollama_provider import OllamaDocumentVisionProvider
from document_understanding.openai_provider import OpenAIDocumentVisionProvider
from document_understanding.provider import (
    ProviderConfigurationError,
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    create_document_provider,
)


GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"


def _payload() -> dict[str, object]:
    return {
        "analysis_status": "usable",
        "document_type": "laboratory collection slip",
        "document_type_confidence": "high",
        "organization": None,
        "purpose": "retrieve_lab_report",
        "likely_action": "view_report_online",
        "urls": [],
        "qr_codes": [],
        "fields": [],
        "dates": [],
        "instructions": [],
        "raw_summary": "A laboratory collection slip.",
        "overall_confidence": "high",
        "warnings": [],
    }


def _completion(*, parsed: object | None = None, content: str | None = None):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(parsed=parsed, content=content)
            )
        ]
    )


class GeminiProviderTests(unittest.TestCase):
    def _provider_with_client(self) -> tuple[GeminiDocumentVisionProvider, MagicMock]:
        client = MagicMock()
        with patch("document_understanding.gemini_provider.OpenAI", return_value=client):
            provider = GeminiDocumentVisionProvider(
                api_key="test-key",
                base_url=GEMINI_BASE_URL,
                model="gemini-3.7-flash",
                timeout_seconds=90,
                reasoning_effort="low",
            )
        return provider, client

    def _image(self, directory: str, suffix: str = ".png") -> Path:
        path = Path(directory) / f"slip{suffix}"
        Image.new("RGB", (20, 20), "white").save(path)
        return path

    def test_client_receives_configured_base_url_and_timeout(self) -> None:
        with patch("document_understanding.gemini_provider.OpenAI") as client_class:
            GeminiDocumentVisionProvider(
                api_key="test-key",
                base_url=GEMINI_BASE_URL,
                model="gemini-3.7-flash",
                timeout_seconds=37,
                reasoning_effort="low",
            )

        client_class.assert_called_once_with(
            api_key="test-key",
            base_url=GEMINI_BASE_URL,
            timeout=37,
            max_retries=0,
        )

    def test_invalid_reasoning_effort_is_rejected_safely(self) -> None:
        with self.assertRaisesRegex(
            ProviderConfigurationError,
            "GEMINI_REASONING_EFFORT",
        ):
            GeminiDocumentVisionProvider(
                api_key="test-key",
                base_url=GEMINI_BASE_URL,
                model="gemini-3.7-flash",
                timeout_seconds=60,
                reasoning_effort="unbounded",
            )

    def test_configured_model_and_structured_schema_are_used(self) -> None:
        provider, client = self._provider_with_client()
        parsed = DocumentUnderstandingResult.model_validate(_payload())
        client.beta.chat.completions.parse.return_value = _completion(parsed=parsed)

        with TemporaryDirectory() as directory:
            result = provider.analyze_document(self._image(directory))

        self.assertEqual(result.document_type, "laboratory collection slip")
        request = client.beta.chat.completions.parse.call_args.kwargs
        self.assertEqual(request["model"], "gemini-3.7-flash")
        self.assertIs(request["response_format"], DocumentUnderstandingResult)
        self.assertEqual(request["reasoning_effort"], "low")

    def test_jpg_jpeg_and_png_use_correct_base64_data_urls(self) -> None:
        expected_mime = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
        }
        for suffix, mime_type in expected_mime.items():
            with self.subTest(suffix=suffix), TemporaryDirectory() as directory:
                provider, client = self._provider_with_client()
                parsed = DocumentUnderstandingResult.model_validate(_payload())
                client.beta.chat.completions.parse.return_value = _completion(parsed=parsed)
                image_path = self._image(directory, suffix)

                provider.analyze_document(image_path)

                request = client.beta.chat.completions.parse.call_args.kwargs
                image_url = request["messages"][1]["content"][1]["image_url"]["url"]
                prefix = f"data:{mime_type};base64,"
                self.assertTrue(image_url.startswith(prefix))
                decoded = base64.b64decode(image_url.removeprefix(prefix))
                self.assertEqual(decoded, image_path.read_bytes())

    def test_valid_parsed_output_is_locally_normalized(self) -> None:
        provider, client = self._provider_with_client()
        payload = _payload()
        payload["warnings"] = ["Check image.", "Check image."]
        client.beta.chat.completions.parse.return_value = _completion(
            parsed=DocumentUnderstandingResult.model_validate(payload)
        )

        with TemporaryDirectory() as directory:
            result = provider.analyze_document(self._image(directory))

        self.assertEqual(result.warnings, ["Check image."])

    def test_unavailable_parse_uses_validated_json_schema_fallback(self) -> None:
        provider, client = self._provider_with_client()
        client.beta.chat.completions.parse.side_effect = AttributeError("unavailable")
        client.chat.completions.create.return_value = _completion(
            content=json.dumps(_payload())
        )

        with TemporaryDirectory() as directory:
            result = provider.analyze_document(self._image(directory))

        self.assertEqual(result.analysis_status.value, "usable")
        request = client.chat.completions.create.call_args.kwargs
        self.assertEqual(request["response_format"]["type"], "json_schema")
        self.assertEqual(request["model"], "gemini-3.7-flash")
        self.assertEqual(request["reasoning_effort"], "low")

    def test_rejected_parse_uses_validated_json_schema_fallback(self) -> None:
        provider, client = self._provider_with_client()
        request = httpx.Request("POST", GEMINI_BASE_URL)
        response = httpx.Response(400, request=request)
        client.beta.chat.completions.parse.side_effect = APIStatusError(
            "structured parse unavailable",
            response=response,
            body=None,
        )
        client.chat.completions.create.return_value = _completion(
            content=json.dumps(_payload())
        )

        with TemporaryDirectory() as directory:
            result = provider.analyze_document(self._image(directory))

        self.assertEqual(result.analysis_status.value, "usable")
        client.chat.completions.create.assert_called_once()

    def test_transient_server_error_is_retried_once(self) -> None:
        provider, client = self._provider_with_client()
        request = httpx.Request("POST", GEMINI_BASE_URL)
        response = httpx.Response(503, request=request)
        client.beta.chat.completions.parse.side_effect = [
            APIStatusError(
                "temporarily unavailable",
                response=response,
                body=None,
            ),
            _completion(
                parsed=DocumentUnderstandingResult.model_validate(_payload())
            ),
        ]

        with TemporaryDirectory() as directory, patch(
            "document_understanding.gemini_provider.sleep"
        ) as retry_sleep:
            result = provider.analyze_document(self._image(directory))

        self.assertEqual(result.analysis_status.value, "usable")
        self.assertEqual(client.beta.chat.completions.parse.call_count, 2)
        retry_sleep.assert_called_once_with(1.0)

    def test_invalid_structured_output_is_rejected(self) -> None:
        provider, client = self._provider_with_client()
        client.beta.chat.completions.parse.return_value = _completion(
            parsed={"document_type": "slip"}
        )

        with TemporaryDirectory() as directory:
            with self.assertRaises(ProviderResponseError):
                provider.analyze_document(self._image(directory))

    def test_empty_structured_output_is_rejected_after_fallback(self) -> None:
        provider, client = self._provider_with_client()
        client.beta.chat.completions.parse.return_value = _completion(parsed=None)
        client.chat.completions.create.return_value = _completion(content=None)

        with TemporaryDirectory() as directory:
            with self.assertRaises(ProviderResponseError):
                provider.analyze_document(self._image(directory))

    def test_authentication_error_is_safe_configuration_error(self) -> None:
        provider, client = self._provider_with_client()
        request = httpx.Request("POST", GEMINI_BASE_URL)
        response = httpx.Response(401, request=request)
        client.beta.chat.completions.parse.side_effect = AuthenticationError(
            "secret test-key was rejected",
            response=response,
            body=None,
        )

        with TemporaryDirectory() as directory, self.assertLogs(
            "document_understanding.gemini_provider", logging.WARNING
        ) as captured:
            with self.assertRaises(ProviderConfigurationError):
                provider.analyze_document(self._image(directory))

        logs = " ".join(captured.output)
        self.assertNotIn("test-key", logs)
        self.assertNotIn("base64", logs)

    def test_timeout_is_reported_separately(self) -> None:
        provider, client = self._provider_with_client()
        client.beta.chat.completions.parse.side_effect = APITimeoutError(
            httpx.Request("POST", GEMINI_BASE_URL)
        )

        with TemporaryDirectory() as directory:
            with self.assertRaises(ProviderTimeoutError):
                provider.analyze_document(self._image(directory))

        self.assertEqual(client.beta.chat.completions.parse.call_count, 1)

    def test_rate_limit_is_temporarily_unavailable(self) -> None:
        provider, client = self._provider_with_client()
        request = httpx.Request("POST", GEMINI_BASE_URL)
        response = httpx.Response(429, request=request)
        client.beta.chat.completions.parse.side_effect = RateLimitError(
            "rate limited",
            response=response,
            body=None,
        )

        with TemporaryDirectory() as directory, patch(
            "document_understanding.gemini_provider.sleep"
        ):
            with self.assertRaises(ProviderUnavailableError):
                provider.analyze_document(self._image(directory))

    def test_connection_error_is_temporarily_unavailable(self) -> None:
        provider, client = self._provider_with_client()
        client.beta.chat.completions.parse.side_effect = APIConnectionError(
            request=httpx.Request("POST", GEMINI_BASE_URL)
        )

        with TemporaryDirectory() as directory, patch(
            "document_understanding.gemini_provider.sleep"
        ):
            with self.assertRaises(ProviderUnavailableError):
                provider.analyze_document(self._image(directory))

    def test_missing_key_fails_before_provider_construction(self) -> None:
        settings = replace(
            get_settings(),
            document_ai_provider="gemini",
            document_ai_model="gemini-3.7-flash",
            gemini_api_key=None,
        )

        with self.assertRaisesRegex(
            ProviderConfigurationError,
            "GEMINI_API_KEY is not configured",
        ):
            create_document_provider(settings)

    def test_factory_switches_between_all_document_providers(self) -> None:
        settings = get_settings()
        with patch("document_understanding.gemini_provider.OpenAI"), patch(
            "document_understanding.openai_provider.OpenAI"
        ):
            gemini = create_document_provider(
                replace(
                    settings,
                    document_ai_provider="gemini",
                    document_ai_model="gemini-3.7-flash",
                    gemini_api_key="test-key",
                    gemini_base_url=GEMINI_BASE_URL,
                )
            )
            openai = create_document_provider(
                replace(
                    settings,
                    document_ai_provider="openai",
                    document_ai_model="test-openai-model",
                    document_ai_api_key="test-key",
                )
            )
            ollama = create_document_provider(
                replace(
                    settings,
                    document_ai_provider="ollama",
                    document_ai_model="qwen3-vl:4b-instruct",
                )
            )

        self.assertIsInstance(gemini, GeminiDocumentVisionProvider)
        self.assertIsInstance(openai, OpenAIDocumentVisionProvider)
        self.assertIsInstance(ollama, OllamaDocumentVisionProvider)


if __name__ == "__main__":
    unittest.main()
