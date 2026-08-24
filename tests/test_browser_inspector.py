import unittest

from browser_agent.inspector import PageInspector
from browser_agent.models import ButtonSemanticAction, PageType


def _snapshot() -> dict[str, object]:
    return {
        "forms": [],
        "inputs": [],
        "buttons": [],
        "links": [],
        "resources": [],
        "messages": [],
        "captchaNodes": 0,
        "iframeHints": [],
        "visibleText": "Online reports",
    }


class BrowserInspectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.inspector = PageInspector()

    def test_login_page_extracts_fields_without_values(self) -> None:
        snapshot = _snapshot()
        snapshot.update(
            {
                "forms": [
                    {
                        "ref": "form_1",
                        "name": "report-login",
                        "method": "post",
                        "action": "https://example.test/session",
                    }
                ],
                "inputs": [
                    {
                        "ref": "input_1",
                        "type": "text",
                        "name": "mrno",
                        "label": "MR Number",
                        "placeholder": "Enter MR No",
                        "required": True,
                        "disabled": False,
                        "readOnly": False,
                        "formRef": "form_1",
                        "value": "MUST-NOT-BE-CAPTURED",
                    },
                    {
                        "ref": "input_2",
                        "type": "password",
                        "name": "accesscode",
                        "label": "Access Code",
                        "required": True,
                        "disabled": False,
                        "readOnly": False,
                        "formRef": "form_1",
                        "value": "SECRET",
                    },
                ],
                "buttons": [
                    {
                        "ref": "button_1",
                        "text": "View Reports",
                        "type": "submit",
                        "disabled": False,
                    }
                ],
                "visibleText": "Online reports\nMR Number\nAccess Code\nView Reports",
            }
        )

        observation = self.inspector.from_snapshot(
            snapshot,
            final_url="https://example.test/reports",
            page_title="Online Reports",
        )

        self.assertEqual(len(observation.input_fields), 2)
        self.assertEqual(len(observation.buttons), 1)
        self.assertTrue(observation.authentication_signals.authentication_required)
        self.assertEqual(observation.authentication_signals.field_count, 2)
        self.assertEqual(observation.page_type, PageType.REPORT_LOGIN_PAGE)
        self.assertEqual(
            observation.buttons[0].semantic_action,
            ButtonSemanticAction.VIEW_REPORT,
        )
        serialized = observation.model_dump_json()
        self.assertNotIn("MUST-NOT-BE-CAPTURED", serialized)
        self.assertNotIn("SECRET", serialized)

    def test_captcha_is_detected_without_bypass(self) -> None:
        snapshot = _snapshot()
        snapshot["captchaNodes"] = 1
        snapshot["visibleText"] = "Please complete the CAPTCHA"

        observation = self.inspector.from_snapshot(
            snapshot,
            final_url="https://example.test/verify",
            page_title="Verification",
        )

        self.assertTrue(observation.verification_signals.captcha_detected)
        self.assertTrue(observation.verification_signals.verification_required)
        self.assertEqual(observation.page_type, PageType.VERIFICATION_PAGE)

    def test_hidden_captcha_markup_does_not_force_verification(self) -> None:
        snapshot = _snapshot()
        snapshot["inputs"] = [
            {
                "ref": "input_1",
                "type": "text",
                "name": "username",
                "placeholder": "Username",
                "required": False,
                "disabled": False,
                "readOnly": False,
            },
            {
                "ref": "input_2",
                "type": "password",
                "name": "password",
                "placeholder": "Password",
                "required": False,
                "disabled": False,
                "readOnly": False,
            },
        ]
        snapshot["buttons"] = [
            {
                "ref": "button_1",
                "text": "Login",
                "type": "submit",
                "disabled": False,
            }
        ]
        snapshot["captchaNodes"] = 0
        snapshot["iframeHints"] = [
            "reCAPTCHA challenge hidden inside account recovery modal"
        ]
        snapshot["visibleText"] = "Sign In"

        observation = self.inspector.from_snapshot(
            snapshot,
            final_url="https://reports.example.test/login",
            page_title="Reports",
        )

        self.assertFalse(observation.verification_signals.verification_required)
        self.assertEqual(observation.page_type, PageType.REPORT_LOGIN_PAGE)

    def test_carousel_next_button_is_not_a_workflow_continue_action(self) -> None:
        snapshot = _snapshot()
        snapshot["buttons"] = [
            {
                "ref": "button_1",
                "text": "Next slide",
                "type": "button",
                "disabled": False,
            }
        ]

        observation = self.inspector.from_snapshot(
            snapshot,
            final_url="https://example.test/",
            page_title="Hospital",
        )

        self.assertEqual(
            observation.buttons[0].semantic_action,
            ButtonSemanticAction.UNKNOWN,
        )

    def test_otp_is_detected(self) -> None:
        snapshot = _snapshot()
        snapshot["inputs"] = [
            {
                "ref": "input_1",
                "type": "text",
                "name": "otp",
                "label": "Verification Code",
                "required": True,
                "disabled": False,
                "readOnly": False,
            }
        ]
        snapshot["visibleText"] = "Enter the one-time password sent by SMS"

        observation = self.inspector.from_snapshot(
            snapshot,
            final_url="https://example.test/otp",
            page_title="Verify",
        )

        self.assertTrue(observation.verification_signals.otp_detected)
        self.assertTrue(observation.verification_signals.verification_required)
        self.assertEqual(observation.page_type, PageType.VERIFICATION_PAGE)

    def test_report_download_link_becomes_candidate_without_action(self) -> None:
        snapshot = _snapshot()
        snapshot["links"] = [
            {
                "ref": "link_1",
                "text": "Download PDF",
                "url": "https://example.test/report.pdf?token=private",
            }
        ]
        snapshot["visibleText"] = "Report ready\nDownload PDF"

        observation = self.inspector.from_snapshot(
            snapshot,
            final_url="https://example.test/reports",
            page_title="Report ready",
        )

        self.assertEqual(len(observation.download_candidates), 1)
        self.assertEqual(observation.download_candidates[0].element_id, "link_1")
        self.assertNotIn("private", observation.links[0].url)

    def test_report_row_context_classifies_view_action_and_extracts_date(self) -> None:
        snapshot = _snapshot()
        snapshot["buttons"] = [
            {
                "ref": "button_1",
                "text": "View",
                "type": "button",
                "disabled": False,
                "context": "Laboratory report 24-Aug-2026 View",
            }
        ]
        snapshot["visibleText"] = "Laboratory reports"

        observation = self.inspector.from_snapshot(
            snapshot,
            final_url="https://example.test/reports",
            page_title="Reports",
        )

        self.assertEqual(
            observation.buttons[0].semantic_action,
            ButtonSemanticAction.VIEW_REPORT,
        )
        self.assertEqual(
            observation.buttons[0].report_date.isoformat(),
            "2026-08-24",
        )
        self.assertEqual(observation.download_candidates, [])

    def test_goodhealth_view_link_is_navigation_with_comma_date(self) -> None:
        snapshot = _snapshot()
        snapshot["links"] = [
            {
                "ref": "link_1",
                "text": "View Report",
                "url": "https://reports.example.test/report/view/123",
                "context": "18 Aug,2026 Culture & Sensitivity View Report",
            }
        ]
        snapshot["visibleText"] = "Patient Medical Record Latest Reports"

        observation = self.inspector.from_snapshot(
            snapshot,
            final_url="https://reports.example.test/records",
            page_title="Patient Medical Record",
        )

        self.assertEqual(observation.page_type, PageType.REPORT_LIST_PAGE)
        self.assertEqual(observation.links[0].report_date.isoformat(), "2026-08-18")
        self.assertEqual(observation.download_candidates, [])

    def test_html_laboratory_report_is_classified_as_viewer(self) -> None:
        snapshot = _snapshot()
        snapshot["visibleText"] = (
            "Laboratory Report\nTest result\nReference range\nValidated result"
        )

        observation = self.inspector.from_snapshot(
            snapshot,
            final_url="https://reports.example.test/report/view/123",
            page_title="Laboratory report",
        )

        self.assertEqual(observation.page_type, PageType.REPORT_VIEWER)

    def test_embedded_pdf_becomes_high_confidence_download_candidate(self) -> None:
        snapshot = _snapshot()
        snapshot["resources"] = [
            {
                "ref": "resource_1",
                "tag": "iframe",
                "url": "https://example.test/private/report.pdf?token=secret",
                "mime": "application/pdf",
                "context": "Report dated 2026-08-24",
            }
        ]
        snapshot["visibleText"] = "Report viewer"

        observation = self.inspector.from_snapshot(
            snapshot,
            final_url="https://example.test/viewer",
            page_title="Report viewer",
        )

        self.assertEqual(observation.page_type, PageType.REPORT_VIEWER)
        self.assertEqual(observation.embedded_resource_count, 1)
        self.assertEqual(len(observation.download_candidates), 1)
        candidate = observation.download_candidates[0]
        self.assertEqual(candidate.element_id, "resource_1")
        self.assertEqual(candidate.likely_file_type, "pdf")
        self.assertNotIn("secret", candidate.model_dump_json())


if __name__ == "__main__":
    unittest.main()
