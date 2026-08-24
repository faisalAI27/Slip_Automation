import unittest

from browser_agent.inspector import PageInspector
from browser_agent.models import ButtonSemanticAction, PageType


def _snapshot() -> dict[str, object]:
    return {
        "forms": [],
        "inputs": [],
        "buttons": [],
        "links": [],
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


if __name__ == "__main__":
    unittest.main()
