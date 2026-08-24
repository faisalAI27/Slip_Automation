from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from PIL import Image

from config.settings import get_settings
from document_understanding.models import (
    AnalysisStatus,
    ConfidenceLevel,
    DocumentUnderstandingResult,
    QRCodeResult,
    QRContentType,
)
from document_understanding.ollama_provider import OllamaDocumentVisionProvider
from document_understanding.parser import DocumentParseError, parse_document_result
from document_understanding.provider import ProviderConfigurationError, create_document_provider
from document_understanding.qr import decode_qr_codes
from document_understanding.service import DocumentUnderstandingService


def _base_payload() -> dict[str, object]:
    return {
        "analysis_status": "usable",
        "document_type": "laboratory report collection slip",
        "document_type_confidence": "high",
        "organization": {
            "name": "Example Diagnostic Centre",
            "type": "diagnostic_center",
            "confidence": "high",
        },
        "purpose": "retrieve_lab_report",
        "likely_action": "view_report_online",
        "urls": [],
        "qr_codes": [],
        "fields": [],
        "dates": [],
        "instructions": [],
        "raw_summary": "A general laboratory collection slip.",
        "overall_confidence": "high",
        "warnings": [],
    }


class StaticProvider:
    def __init__(self, result: DocumentUnderstandingResult) -> None:
        self.result = result

    def analyze_document(self, image_path: Path) -> DocumentUnderstandingResult:
        return self.result


class DocumentUnderstandingTests(unittest.TestCase):
    def test_case_a_hospital_url_identifiers_and_credential(self) -> None:
        payload = _base_payload()
        payload.update(
            {
                "organization": {
                    "name": "Example General Hospital",
                    "type": "hospital",
                    "confidence": "high",
                },
                "urls": [
                    {
                        "url": "www.example.test/reports",
                        "normalized_url": None,
                        "context": "Below the online reports heading",
                        "likely_purpose": "report_portal",
                        "confidence": "high",
                    },
                    {
                        "url": "https://www.example.test/reports/",
                        "normalized_url": "https://www.example.test/reports/",
                        "context": None,
                        "likely_purpose": "report_portal",
                        "confidence": "medium",
                    },
                ],
                "fields": [
                    {
                        "label": "MR No",
                        "value": "839281",
                        "semantic_type": "patient_identifier",
                        "confidence": "high",
                    },
                    {
                        "label": "Online Code",
                        "value": "72914",
                        "semantic_type": "access_credential",
                        "confidence": "high",
                    },
                ],
                "dates": [
                    {
                        "label": "Collection Date",
                        "value": "21-08-2026",
                        "semantic_type": "collection_date",
                        "confidence": "high",
                    }
                ],
                "instructions": ["Use the MR number and online code to view reports."],
            }
        )

        result = parse_document_result(payload)

        self.assertEqual(len(result.urls), 1)
        self.assertEqual(result.urls[0].normalized_url, "https://www.example.test/reports")
        self.assertEqual(len(result.fields), 2)
        self.assertEqual(result.fields[1].semantic_type.value, "access_credential")

    def test_case_b_qr_is_merged_without_printed_url(self) -> None:
        payload = _base_payload()
        payload["organization"] = {
            "name": "Example Laboratory",
            "type": "laboratory",
            "confidence": "high",
        }
        payload["fields"] = [
            {
                "label": "Registration Number",
                "value": "REG-1002",
                "semantic_type": "registration_identifier",
                "confidence": "high",
            }
        ]
        provider_result = parse_document_result(payload)
        decoded = QRCodeResult(
            value="https://example.test/r/REG-1002",
            type=QRContentType.URL,
            confidence=ConfidenceLevel.HIGH,
            symbol_format="QRCode",
        )
        service = DocumentUnderstandingService(
            StaticProvider(provider_result), qr_decoder=lambda _: ([decoded], [])
        )

        result = service.analyze(Path("synthetic.png"))

        self.assertEqual(result.urls, [])
        self.assertEqual(result.qr_codes[0].type, QRContentType.URL)

    def test_case_c_missing_url_and_access_code_is_valid(self) -> None:
        payload = _base_payload()
        payload["fields"] = [
            {
                "label": "Patient Number",
                "value": "PAT-220",
                "semantic_type": "patient_identifier",
                "confidence": "medium",
            }
        ]
        payload["instructions"] = ["Present this document at the collection desk."]

        result = parse_document_result(payload)

        self.assertFalse(result.urls)
        self.assertFalse(
            any(item.semantic_type.value == "access_credential" for item in result.fields)
        )

    def test_case_d_unclear_result_preserves_uncertainty(self) -> None:
        payload = _base_payload()
        payload.update(
            {
                "analysis_status": "unclear",
                "document_type": "unknown",
                "document_type_confidence": "low",
                "organization": None,
                "purpose": "unknown",
                "likely_action": "unknown",
                "raw_summary": "The image is too blurred for reliable interpretation.",
                "overall_confidence": "low",
                "warnings": ["Most text is unreadable.", "Most text is unreadable."],
            }
        )

        result = parse_document_result(payload)

        self.assertEqual(result.analysis_status, AnalysisStatus.UNCLEAR)
        self.assertIsNone(result.organization)
        self.assertEqual(result.warnings, ["Most text is unreadable."])

    def test_malformed_provider_output_has_safe_error(self) -> None:
        with self.assertRaises(DocumentParseError):
            parse_document_result({"document_type": "slip"})

    def test_missing_api_key_fails_before_any_api_call(self) -> None:
        settings = replace(
            get_settings(), document_ai_provider="openai", document_ai_api_key=None
        )
        with self.assertRaises(ProviderConfigurationError):
            create_document_provider(settings)

    def test_ollama_provider_does_not_require_api_key(self) -> None:
        settings = replace(
            get_settings(),
            document_ai_provider="ollama",
            document_ai_model="qwen3-vl:4b-instruct",
            document_ai_api_key=None,
        )

        provider = create_document_provider(settings)

        self.assertIsInstance(provider, OllamaDocumentVisionProvider)

    def test_image_without_qr_returns_empty_result(self) -> None:
        with TemporaryDirectory() as directory:
            image_path = Path(directory) / "plain.png"
            Image.new("RGB", (160, 120), "white").save(image_path)

            codes, warnings = decode_qr_codes(image_path)

        self.assertEqual(codes, [])
        self.assertEqual(warnings, [])


if __name__ == "__main__":
    unittest.main()
