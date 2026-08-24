import unittest

from document_understanding.models import DocumentUnderstandingResult
from workflow.models import (
    ActionType,
    PlanningStatus,
    PortalSource,
    PortalStrategy,
)
from workflow.planner import WorkflowPlanner
from workflow.validation import PlanningValidationError, validate_search_query


def _payload() -> dict[str, object]:
    return {
        "analysis_status": "usable",
        "document_type": "laboratory collection slip",
        "document_type_confidence": "high",
        "organization": {
            "name": "Example Diagnostic Centre",
            "type": "diagnostic_center",
            "confidence": "high",
        },
        "purpose": "retrieve laboratory report",
        "likely_action": "view report online",
        "urls": [],
        "qr_codes": [],
        "fields": [
            {
                "label": "MR No",
                "value": "MR-123456",
                "semantic_type": "patient_identifier",
                "confidence": "high",
            },
            {
                "label": "Online Code",
                "value": "88219",
                "semantic_type": "access_credential",
                "confidence": "high",
            },
        ],
        "dates": [],
        "instructions": [],
        "raw_summary": "A laboratory collection slip.",
        "overall_confidence": "high",
        "warnings": [],
    }


def _result(payload: dict[str, object]) -> DocumentUnderstandingResult:
    return DocumentUnderstandingResult.model_validate(payload)


class WorkflowPlannerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.planner = WorkflowPlanner()

    def test_explicit_report_url_is_first_action(self) -> None:
        payload = _payload()
        payload["urls"] = [
            {
                "url": "https://example.test/reports",
                "normalized_url": "https://example.test/reports",
                "context": "Online reports",
                "likely_purpose": "report_portal",
                "confidence": "high",
            }
        ]

        plan = self.planner.plan(_result(payload))

        self.assertEqual(plan.status, PlanningStatus.READY)
        self.assertEqual(plan.required_next_action.type, ActionType.OPEN_URL)
        self.assertEqual(plan.portal_strategy, PortalStrategy.EXPLICIT_REPORT_URL)
        self.assertEqual(len(plan.available_fields), 2)

    def test_known_organization_without_url_generates_safe_search(self) -> None:
        plan = self.planner.plan(_result(_payload()))

        self.assertEqual(plan.status, PlanningStatus.SEARCH_REQUIRED)
        self.assertEqual(plan.required_next_action.type, ActionType.SEARCH_WEB)
        query = plan.required_next_action.query or ""
        self.assertIn("Example Diagnostic Centre", query)
        self.assertNotIn("MR-123456", query)
        self.assertNotIn("88219", query)

    def test_qr_report_url_is_selected(self) -> None:
        payload = _payload()
        payload["qr_codes"] = [
            {
                "value": "https://example.test/patient/reports",
                "type": "url",
                "confidence": "high",
                "symbol_format": "QRCode",
            }
        ]

        plan = self.planner.plan(_result(payload))

        self.assertEqual(plan.status, PlanningStatus.READY)
        self.assertEqual(plan.portal_strategy, PortalStrategy.QR_REPORT_URL)
        self.assertEqual(plan.portal_candidates[0].source, PortalSource.QR_CODE)
        self.assertEqual(plan.required_next_action.type, ActionType.OPEN_URL)

    def test_organization_homepage_is_selected_for_future_inspection(self) -> None:
        payload = _payload()
        payload["urls"] = [
            {
                "url": "https://example.test",
                "normalized_url": "https://example.test",
                "context": "Organization website",
                "likely_purpose": "organization_homepage",
                "confidence": "high",
            }
        ]

        plan = self.planner.plan(_result(payload))

        self.assertEqual(plan.status, PlanningStatus.READY)
        self.assertEqual(plan.portal_strategy, PortalStrategy.ORGANIZATION_HOMEPAGE)
        self.assertEqual(plan.required_next_action.type, ActionType.OPEN_URL)

    def test_unknown_organization_without_url_requires_user_input(self) -> None:
        payload = _payload()
        payload["organization"] = None

        plan = self.planner.plan(_result(payload))

        self.assertEqual(plan.status, PlanningStatus.USER_INPUT_REQUIRED)
        self.assertEqual(plan.required_next_action.type, ActionType.STOP)
        self.assertTrue(plan.user_input_requirement.required)

    def test_search_validation_rejects_sensitive_values(self) -> None:
        with self.assertRaises(PlanningValidationError):
            validate_search_query(
                "Example Diagnostic Centre 123456 reports", ["MR-123456"]
            )

    def test_unrelated_qr_url_is_not_trusted(self) -> None:
        payload = _payload()
        payload["qr_codes"] = [
            {
                "value": "https://unrelated.example/promotions",
                "type": "url",
                "confidence": "high",
                "symbol_format": "QRCode",
            }
        ]

        plan = self.planner.plan(_result(payload))

        self.assertEqual(plan.status, PlanningStatus.SEARCH_REQUIRED)
        self.assertEqual(plan.portal_candidates, [])

    def test_duplicate_urls_collapse_into_one_candidate(self) -> None:
        payload = _payload()
        payload["urls"] = [
            {
                "url": "https://EXAMPLE.test/reports/",
                "normalized_url": "https://EXAMPLE.test/reports/",
                "context": None,
                "likely_purpose": "report_portal",
                "confidence": "high",
            },
            {
                "url": "https://example.test/reports",
                "normalized_url": "https://example.test/reports",
                "context": None,
                "likely_purpose": "report_portal",
                "confidence": "medium",
            },
        ]

        plan = self.planner.plan(_result(payload))

        self.assertEqual(len(plan.portal_candidates), 1)

    def test_unsafe_url_scheme_is_never_selected(self) -> None:
        payload = _payload()
        payload["organization"] = None
        payload["qr_codes"] = [
            {
                "value": "javascript:alert(1)",
                "type": "url",
                "confidence": "high",
                "symbol_format": "QRCode",
            }
        ]

        plan = self.planner.plan(_result(payload))

        self.assertEqual(plan.status, PlanningStatus.USER_INPUT_REQUIRED)
        self.assertEqual(plan.portal_candidates, [])
        self.assertTrue(any("safe HTTP(S)" in warning for warning in plan.warnings))

    def test_non_medical_document_is_unsupported(self) -> None:
        payload = _payload()
        payload["analysis_status"] = "not_medical"

        plan = self.planner.plan(_result(payload))

        self.assertEqual(plan.status, PlanningStatus.UNSUPPORTED)
        self.assertEqual(plan.required_next_action.type, ActionType.STOP)

    def test_user_provided_bare_domain_becomes_one_safe_open_action(self) -> None:
        result = _result(_payload())

        plan = self.planner.plan_user_provided_url(
            result, "reports.example.test/login"
        )

        self.assertEqual(plan.status, PlanningStatus.READY)
        self.assertEqual(plan.portal_strategy, PortalStrategy.USER_PROVIDED_URL)
        self.assertEqual(plan.portal_candidates[0].source, PortalSource.USER_PROVIDED_URL)
        self.assertEqual(
            plan.required_next_action.target,
            "https://reports.example.test/login",
        )
        self.assertNotIn("MR-123456", plan.required_next_action.target or "")

    def test_invalid_user_provided_website_is_rejected(self) -> None:
        with self.assertRaises(PlanningValidationError):
            self.planner.plan_user_provided_url(_result(_payload()), "not a website")


if __name__ == "__main__":
    unittest.main()
