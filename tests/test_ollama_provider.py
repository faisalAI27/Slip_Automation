import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

import httpx
from ollama import ResponseError
from PIL import Image

from document_understanding.models import AnalysisStatus, DocumentUnderstandingResult
from document_understanding.ollama_provider import OllamaDocumentVisionProvider
from document_understanding.provider import (
    ProviderConfigurationError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)


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


class RecordingClient:
    def __init__(self, content: str) -> None:
        self.content = content
        self.request: dict[str, object] | None = None

    def chat(self, **kwargs: object) -> object:
        self.request = kwargs
        return SimpleNamespace(message=SimpleNamespace(content=self.content))


class FailingClient:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def chat(self, **kwargs: object) -> object:
        raise self.error


class OllamaProviderTests(unittest.TestCase):
    def _provider(self) -> OllamaDocumentVisionProvider:
        return OllamaDocumentVisionProvider(
            base_url="http://127.0.0.1:11434",
            model="qwen3-vl:2b-instruct",
            timeout_seconds=30,
        )

    def test_sends_image_and_schema_then_parses_result(self) -> None:
        client = RecordingClient(json.dumps(_payload()))
        provider = self._provider()
        provider._client = client

        with TemporaryDirectory() as directory:
            image_path = Path(directory) / "slip.png"
            Image.new("RGB", (160, 120), "white").save(image_path)
            result = provider.analyze_document(image_path)

        self.assertEqual(result.analysis_status, AnalysisStatus.USABLE)
        assert client.request is not None
        self.assertEqual(client.request["model"], "qwen3-vl:2b-instruct")
        self.assertEqual(
            client.request["format"], DocumentUnderstandingResult.model_json_schema()
        )
        messages = client.request["messages"]
        self.assertEqual(messages[0]["images"], [str(image_path)])
        self.assertEqual(client.request["options"]["temperature"], 0)

    def test_connection_failure_is_classified_as_unavailable(self) -> None:
        provider = self._provider()
        provider._client = FailingClient(ConnectionError("offline"))

        with TemporaryDirectory() as directory:
            image_path = Path(directory) / "slip.png"
            Image.new("RGB", (20, 20), "white").save(image_path)
            with self.assertRaises(ProviderUnavailableError):
                provider.analyze_document(image_path)

    def test_timeout_is_reported_separately_from_offline(self) -> None:
        provider = self._provider()
        provider._client = FailingClient(httpx.ReadTimeout("slow local model"))

        with TemporaryDirectory() as directory:
            image_path = Path(directory) / "slip.png"
            Image.new("RGB", (20, 20), "white").save(image_path)
            with self.assertRaises(ProviderTimeoutError):
                provider.analyze_document(image_path)

    def test_missing_model_is_a_configuration_error(self) -> None:
        provider = self._provider()
        provider._client = FailingClient(ResponseError("model not found", 404))

        with TemporaryDirectory() as directory:
            image_path = Path(directory) / "slip.png"
            Image.new("RGB", (20, 20), "white").save(image_path)
            with self.assertRaises(ProviderConfigurationError):
                provider.analyze_document(image_path)


if __name__ == "__main__":
    unittest.main()
