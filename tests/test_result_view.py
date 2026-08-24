import unittest

from streamlit.testing.v1 import AppTest


RESULT_PAYLOAD = {
    "analysis_status": "usable",
    "document_type": "laboratory slip",
    "document_type_confidence": "high",
    "organization": {
        "name": "Example Laboratory",
        "type": "laboratory",
        "confidence": "high",
    },
    "purpose": "retrieve report",
    "likely_action": "open report portal",
    "urls": [
        {
            "url": "www.example.test",
            "normalized_url": "https://www.example.test",
            "context": None,
            "likely_purpose": "report_portal",
            "confidence": "high",
        }
    ],
    "qr_codes": [],
    "fields": [
        {
            "label": "MR Number",
            "value": "MR-123",
            "semantic_type": "patient_identifier",
            "confidence": "high",
        }
    ],
    "dates": [],
    "instructions": ["Use the MR number."],
    "raw_summary": "A laboratory slip.",
    "overall_confidence": "high",
    "warnings": [],
}


class ResultViewTests(unittest.TestCase):
    def test_extracted_values_are_visible_without_opening_links(self) -> None:
        source = (
            "from ui.result_view import render_extracted_document\n"
            f"render_extracted_document({RESULT_PAYLOAD!r})\n"
        )

        app = AppTest.from_string(source).run(timeout=15)

        self.assertFalse(app.exception)
        self.assertIn("What was extracted", [item.value for item in app.subheader])
        self.assertIn("MR-123", [item.value for item in app.code])
        self.assertIn("https://www.example.test", [item.value for item in app.code])
        self.assertEqual(len(app.get("link_button")), 0)
        self.assertTrue(
            any("patient details" in item.value for item in app.warning)
        )


if __name__ == "__main__":
    unittest.main()
