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

    def test_failed_portal_attempt_shows_extracted_url_and_reason(self) -> None:
        plan = {
            "goal": "Retrieve a report.",
            "status": "ready",
            "organization": {
                "name": "Example Laboratory",
                "type": "laboratory",
                "confidence": "high",
            },
            "portal_strategy": "explicit_report_url",
            "portal_candidates": [
                {
                    "url": "https://www.example.test/",
                    "source": "printed_url",
                    "likely_purpose": "report_portal",
                    "confidence": "high",
                    "reason": "Printed report URL.",
                }
            ],
            "available_fields": [],
            "required_next_action": {
                "type": "open_url",
                "target": "https://www.example.test/",
                "query": None,
                "reason": "Printed report URL.",
                "confidence": "high",
            },
            "user_input_requirement": {
                "required": False,
                "reason": None,
                "requested_information": [],
            },
            "warnings": [],
            "planner_summary": "A URL is available.",
        }
        browser_result = {
            "action_type": "open_url",
            "success": False,
            "requested_target_type": "url",
            "requested_target": "https://www.example.test/",
            "final_url": None,
            "final_domain": None,
            "redirect_occurred": False,
            "redirects": [],
            "observation": None,
            "search_observation": None,
            "warnings": [],
            "error_type": "unsafe_navigation",
            "error_message": "The destination hostname could not be verified.",
        }
        source = (
            "from ui.result_view import render_portal_attempt_details\n"
            f"render_portal_attempt_details({RESULT_PAYLOAD!r}, {plan!r}, "
            f"{browser_result!r})\n"
        )

        app = AppTest.from_string(source).run(timeout=15)

        self.assertFalse(app.exception)
        self.assertIn("www.example.test", [item.value for item in app.code])
        self.assertIn("https://www.example.test", [item.value for item in app.code])
        self.assertTrue(
            any(
                "hostname could not be verified" in item.value
                for item in app.markdown
            )
        )


if __name__ == "__main__":
    unittest.main()
