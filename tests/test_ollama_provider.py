import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

import httpx
from ollama import ResponseError
from PIL import Image

from document_understanding.models import AnalysisStatus, DocumentUnderstandingResult
from document_understanding.ollama_provider import (
    CREDENTIAL_FOCUS_SCHEMA,
    OllamaDocumentVisionProvider,
)
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


class SequentialClient:
    def __init__(self, contents: list[str]) -> None:
        self.contents = list(contents)
        self.requests: list[dict[str, object]] = []

    def chat(self, **kwargs: object) -> object:
        self.requests.append(kwargs)
        return SimpleNamespace(
            message=SimpleNamespace(content=self.contents.pop(0))
        )


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
        self.assertIn("USER ID", messages[0]["content"])
        self.assertIn("access_credential", messages[0]["content"])
        self.assertFalse(client.request["think"])
        self.assertEqual(client.request["options"]["temperature"], 0)
        self.assertEqual(client.request["options"]["num_ctx"], 6144)
        self.assertEqual(client.request["options"]["num_predict"], 2048)

    def test_connection_failure_is_classified_as_unavailable(self) -> None:
        provider = self._provider()
        provider._client = FailingClient(ConnectionError("offline"))

        with TemporaryDirectory() as directory:
            image_path = Path(directory) / "slip.png"
            Image.new("RGB", (20, 20), "white").save(image_path)
            with self.assertRaises(ProviderUnavailableError):
                provider.analyze_document(image_path)

    def test_report_portal_missing_credentials_gets_focused_supplement(self) -> None:
        initial = _payload()
        initial["urls"] = [
            {
                "url": "https://reports.example.test",
                "normalized_url": "https://reports.example.test",
                "context": "E-report",
                "likely_purpose": "report_portal",
                "confidence": "high",
            }
        ]
        initial["instructions"] = [
            "Use the USER ID and PASSWORD for the online report."
        ]
        focused = {
            "fields": [
                {"label": "USER ID", "value": "PRIVATE-ID", "confidence": "high"},
                {
                    "label": "PASSWORD",
                    "value": "PRIVATE-PASSWORD",
                    "confidence": "high",
                },
            ]
        }
        client = SequentialClient([json.dumps(initial), json.dumps(focused)])
        provider = self._provider()
        provider._client = client

        with TemporaryDirectory() as directory:
            image_path = Path(directory) / "slip.png"
            Image.new("RGB", (160, 120), "white").save(image_path)
            result = provider.analyze_document(image_path)

        self.assertEqual(len(client.requests), 2)
        fields = {item.label: item for item in result.fields}
        self.assertEqual(
            fields["USER ID"].semantic_type.value,
            "patient_identifier",
        )
        self.assertEqual(
            fields["PASSWORD"].semantic_type.value,
            "access_credential",
        )
        self.assertEqual(client.requests[1]["format"], CREDENTIAL_FOCUS_SCHEMA)

    def test_focused_high_confidence_credentials_replace_general_values(self) -> None:
        initial = _payload()
        initial["urls"] = [
            {
                "url": "https://reports.example.test",
                "normalized_url": "https://reports.example.test",
                "context": "Online reports",
                "likely_purpose": "report_portal",
                "confidence": "high",
            }
        ]
        initial["fields"] = [
            {
                "label": "USER ID",
                "value": "GENERAL-ID",
                "semantic_type": "patient_identifier",
                "confidence": "high",
            },
            {
                "label": "PASSWORD",
                "value": "GENERAL-PASSWORD",
                "semantic_type": "access_credential",
                "confidence": "high",
            },
        ]
        focused = {
            "fields": [
                {"label": "USER ID", "value": "FOCUSED-ID", "confidence": "high"},
                {
                    "label": "PASSWORD",
                    "value": "FOCUSED-PASSWORD",
                    "confidence": "high",
                },
            ]
        }
        client = SequentialClient([json.dumps(initial), json.dumps(focused)])
        provider = self._provider()
        provider._client = client

        with TemporaryDirectory() as directory:
            image_path = Path(directory) / "slip.png"
            Image.new("RGB", (160, 120), "white").save(image_path)
            result = provider.analyze_document(image_path)

        fields = {item.label: item for item in result.fields}
        self.assertEqual(fields["USER ID"].value, "FOCUSED-ID")
        self.assertEqual(fields["PASSWORD"].value, "FOCUSED-PASSWORD")
        self.assertEqual(len(client.requests), 2)

    def test_focused_credentials_replace_equivalent_general_label_variants(self) -> None:
        initial = _payload()
        initial["urls"] = [
            {
                "url": "https://reports.example.test",
                "normalized_url": "https://reports.example.test",
                "context": "Online reports",
                "likely_purpose": "report_portal",
                "confidence": "high",
            }
        ]
        initial["fields"] = [
            {
                "label": "E-REPORT USER ID",
                "value": "GENERAL-ID",
                "semantic_type": "patient_identifier",
                "confidence": "high",
            },
            {
                "label": "E-REPORT PASSWORD",
                "value": "GENERAL-PASSWORD",
                "semantic_type": "access_credential",
                "confidence": "high",
            },
        ]
        focused = {
            "fields": [
                {"label": "USER ID", "value": "FOCUSED-ID", "confidence": "high"},
                {
                    "label": "PASSWORD",
                    "value": "FOCUSED-PASSWORD",
                    "confidence": "high",
                },
            ]
        }
        client = SequentialClient([json.dumps(initial), json.dumps(focused)])
        provider = self._provider()
        provider._client = client

        with TemporaryDirectory() as directory:
            image_path = Path(directory) / "slip.png"
            Image.new("RGB", (160, 120), "white").save(image_path)
            result = provider.analyze_document(image_path)

        login_fields = [
            item
            for item in result.fields
            if item.label and "USER ID" in item.label.upper()
        ]
        secret_fields = [
            item
            for item in result.fields
            if item.semantic_type.value == "access_credential"
        ]
        self.assertEqual(len(login_fields), 1)
        self.assertEqual(len(secret_fields), 1)
        self.assertEqual(login_fields[0].value, "FOCUSED-ID")
        self.assertEqual(secret_fields[0].value, "FOCUSED-PASSWORD")

    def test_explicit_password_label_corrects_model_semantic_type(self) -> None:
        initial = _payload()
        initial["fields"] = [
            {
                "label": "USER ID",
                "value": "PRIVATE-ID",
                "semantic_type": "organization_identifier",
                "confidence": "high",
            },
            {
                "label": "PASSWORD",
                "value": "PRIVATE-PASSWORD",
                "semantic_type": "patient_identifier",
                "confidence": "high",
            },
        ]
        client = RecordingClient(json.dumps(initial))
        provider = self._provider()
        provider._client = client

        with TemporaryDirectory() as directory:
            image_path = Path(directory) / "slip.png"
            Image.new("RGB", (160, 120), "white").save(image_path)
            result = provider.analyze_document(image_path)

        fields = {item.label: item for item in result.fields}
        self.assertEqual(
            fields["USER ID"].semantic_type.value,
            "patient_identifier",
        )
        self.assertEqual(
            fields["PASSWORD"].semantic_type.value,
            "access_credential",
        )

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
