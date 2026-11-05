from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from browser_agent.field_matcher import DocumentFieldStore, FieldMatcher
from browser_agent.models import HtmlInputType
from config.settings import get_settings
from document_understanding.hospitals import Hospital, analysis_prompt, focused_document
from document_understanding.models import DocumentUnderstandingResult
from document_understanding.provider import create_document_provider
from document_understanding.prompts import DOCUMENT_ANALYSIS_PROMPT
from services.models import RetrievalOutcomeStatus
from services.report_retrieval import ReportRetrievalService
from tests.test_document_understanding import _base_payload
from tests.test_field_matcher import _page_field
from workflow.models import ActionType, PlanningStatus


def document(hospital, *, missing=False):
    payload = deepcopy(_base_payload())
    payload["organization"]["name"] = (
        "Northwest General Hospital"
        if hospital == Hospital.NORTHWEST
        else "Rehman Medical Institute"
    )
    labels = (
        ("Invoice No.", "Access Code")
        if hospital == Hospital.NORTHWEST
        else ("USER ID", "PASSWORD")
    )
    payload["fields"] = [
        {
            "label": label,
            "value": value,
            "semantic_type": "unknown",
            "confidence": "high",
        }
        for label, value in zip(labels, ("LOGIN-123", "SECRET-456"))
    ]
    if missing:
        payload["fields"].pop()
    payload["fields"].append(
        {
            "label": "MR No.",
            "value": "UNRELATED-789",
            "semantic_type": "patient_identifier",
            "confidence": "high",
        }
    )
    return DocumentUnderstandingResult.model_validate(payload)


class HospitalProfileTests(unittest.TestCase):
    def setUp(self):
        self.settings = replace(get_settings(), portal_url_overrides={})
        self.service = ReportRetrievalService(self.settings)

    def test_profiles_target_only_their_two_fields_and_official_portals(self):
        for hospital, url, labels in (
            (
                Hospital.NORTHWEST,
                "https://reports.nwgh.pk/",
                ("Invoice No.", "Access Code"),
            ),
            (Hospital.RMI, "https://labreports.rmi.edu.pk/", ("Username", "Password")),
        ):
            with self.subTest(hospital=hospital):
                plan = self.service.plan_workflow(document(hospital), hospital)
                self.assertEqual(plan.status, PlanningStatus.READY)
                self.assertEqual(plan.required_next_action.target, url)
                self.assertEqual(len(plan.available_fields), 2)
                self.assertNotIn("UNRELATED-789", plan.model_dump_json())
                store = DocumentFieldStore(plan.available_fields)
                mapping = FieldMatcher().match(
                    store.descriptors,
                    [
                        _page_field("input_1", labels[0]),
                        _page_field(
                            "input_2",
                            labels[1],
                            html_type=(
                                HtmlInputType.TEXT
                                if hospital == Hospital.NORTHWEST
                                else HtmlInputType.PASSWORD
                            ),
                        ),
                    ],
                )
                self.assertTrue(mapping.actionable)
                self.assertEqual(len(mapping.matches), 2)

    def test_missing_low_confidence_or_conflicting_fields_stop_before_browser(self):
        for hospital in (Hospital.NORTHWEST, Hospital.RMI):
            missing = document(hospital, missing=True)
            uncertain = document(hospital)
            uncertain.fields[1].confidence = "low"
            conflicting = document(hospital)
            conflicting.fields.append(
                conflicting.fields[0].model_copy(update={"value": "OTHER-READ"})
            )
            for result in (missing, uncertain, conflicting):
                with self.subTest(hospital=hospital, result=result.fields[0].label):
                    plan = self.service.plan_workflow(result, hospital)
                    self.assertEqual(plan.status, PlanningStatus.USER_INPUT_REQUIRED)
                    self.assertEqual(plan.required_next_action.type, ActionType.STOP)
                    self.assertIsNone(plan.required_next_action.target)

    def test_wrong_hospital_stops_even_with_matching_field_labels(self):
        result = document(Hospital.NORTHWEST)
        result.organization.name = "Rehman Medical Institute"
        plan = self.service.plan_workflow(result, Hospital.NORTHWEST)
        self.assertEqual(plan.status, PlanningStatus.USER_INPUT_REQUIRED)
        self.assertIn("correct hospital", plan.user_input_requirement.reason)

    def test_invoice_totals_and_combined_login_labels_are_not_credentials(self):
        result = document(Hospital.NORTHWEST)
        result.fields[0].label = "Invoice Total"
        self.assertEqual(
            self.service.plan_workflow(result, Hospital.NORTHWEST).status,
            PlanningStatus.USER_INPUT_REQUIRED,
        )
        result = document(Hospital.RMI)
        result.fields = [
            result.fields[0].model_copy(update={"label": "Username / Password"})
        ]
        self.assertEqual(
            self.service.plan_workflow(result, Hospital.RMI).status,
            PlanningStatus.USER_INPUT_REQUIRED,
        )

    def test_non_medical_and_unclear_documents_cannot_get_ready_profile_plan(self):
        for status in ("not_medical", "unclear", "unknown"):
            result = document(Hospital.RMI)
            result.analysis_status = status
            self.assertNotEqual(
                self.service.plan_workflow(result, Hospital.RMI).status,
                PlanningStatus.READY,
            )

    def test_configured_legacy_portal_is_respected_without_enabling_http(self):
        url = "http://reports.nwgh.pk:8086/Forms/InvestigatonOnline.aspx"
        settings = replace(self.settings, portal_url_overrides={"nwgh.pk": url})
        plan = ReportRetrievalService(settings).plan_workflow(
            document(Hospital.NORTHWEST), Hospital.NORTHWEST
        )
        self.assertEqual(plan.required_next_action.target, url)
        self.assertEqual(
            settings.allow_insecure_report_portals,
            self.settings.allow_insecure_report_portals,
        )

    def test_general_mode_preserves_original_document_and_discovery(self):
        result = document(Hospital.RMI)
        self.assertIs(focused_document(result, Hospital.OTHER), result)
        self.assertEqual(analysis_prompt(Hospital.OTHER), DOCUMENT_ANALYSIS_PROMPT)
        plan = self.service.plan_workflow(result)
        self.assertEqual(plan.status, PlanningStatus.SEARCH_REQUIRED)
        self.assertEqual(len(plan.available_fields), 3)

    def test_missing_profile_fields_never_call_retrieval_agent(self):
        document_service = Mock()
        document_service.analyze.return_value = document(
            Hospital.NORTHWEST, missing=True
        )
        agent = Mock()
        service = ReportRetrievalService(
            self.settings, document_service=document_service, retrieval_agent=agent
        )
        outcome = service.retrieve(Path("synthetic.png"), hospital=Hospital.NORTHWEST)
        self.assertEqual(outcome.status, RetrievalOutcomeStatus.USER_INPUT_REQUIRED)
        agent.run.assert_not_called()

    def test_provider_factory_supplies_focused_prompt_for_every_provider(self):
        for provider, target in (
            (
                "ollama",
                "document_understanding.ollama_provider.OllamaDocumentVisionProvider",
            ),
            (
                "gemini",
                "document_understanding.gemini_provider.GeminiDocumentVisionProvider",
            ),
            (
                "openai",
                "document_understanding.openai_provider.OpenAIDocumentVisionProvider",
            ),
        ):
            settings = replace(
                self.settings,
                document_ai_provider=provider,
                gemini_api_key="synthetic",
                document_ai_api_key="synthetic",
            )
            with self.subTest(provider=provider), patch(target) as factory:
                create_document_provider(settings, Hospital.NORTHWEST)
                self.assertIn(
                    "Invoice No.", factory.call_args.kwargs["analysis_prompt"]
                )


if __name__ == "__main__":
    unittest.main()
