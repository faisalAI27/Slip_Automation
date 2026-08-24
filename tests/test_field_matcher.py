import unittest

from browser_agent.field_matcher import DocumentFieldStore, FieldMatcher
from browser_agent.models import HtmlInputType, InputFieldObservation, UserProvidedField
from document_understanding.models import ConfidenceLevel, FieldSemanticType
from workflow.models import AvailableField, InformationSource, PotentialUse


def _document_field(label: str, semantic_type: FieldSemanticType, value: str = "secret"):
    return AvailableField(
        label=label,
        value=value,
        semantic_type=semantic_type,
        source=InformationSource.DOCUMENT_FIELD,
        potential_use=(
            PotentialUse.PORTAL_AUTHENTICATION
            if semantic_type == FieldSemanticType.ACCESS_CREDENTIAL
            else PotentialUse.PORTAL_FORM_INPUT
        ),
        confidence=ConfidenceLevel.HIGH,
    )


def _page_field(
    ref: str,
    label: str,
    *,
    html_type: HtmlInputType = HtmlInputType.TEXT,
    required: bool = True,
):
    return InputFieldObservation(
        element_id=ref,
        html_type=html_type,
        name=None,
        label=label,
        placeholder=None,
        aria_label=None,
        required=required,
        disabled=False,
        readonly=False,
        autocomplete=None,
    )


class FieldMatcherTests(unittest.TestCase):
    def test_standard_report_login_matches_without_exposing_values(self) -> None:
        store = DocumentFieldStore(
            [
                _document_field("MR No", FieldSemanticType.PATIENT_IDENTIFIER, "MR-123"),
                _document_field("Access Code", FieldSemanticType.ACCESS_CREDENTIAL, "9988"),
            ]
        )
        result = FieldMatcher().match(
            store.descriptors,
            [
                _page_field("input_1", "Patient Number"),
                _page_field("input_2", "Web Password", html_type=HtmlInputType.PASSWORD),
            ],
        )

        self.assertTrue(result.actionable)
        self.assertEqual(len(result.matches), 2)
        self.assertTrue(all(item.confidence == ConfidenceLevel.HIGH for item in result.matches))
        serialized = result.model_dump_json()
        self.assertNotIn("MR-123", serialized)
        self.assertNotIn("9988", serialized)

    def test_different_general_terminology_matches(self) -> None:
        store = DocumentFieldStore(
            [
                _document_field("Registration No", FieldSemanticType.REGISTRATION_IDENTIFIER),
                _document_field("Online Code", FieldSemanticType.ACCESS_CREDENTIAL),
            ]
        )

        result = FieldMatcher().match(
            store.descriptors,
            [
                _page_field("input_1", "Patient ID"),
                _page_field("input_2", "Report PIN", html_type=HtmlInputType.PASSWORD),
            ],
        )

        self.assertTrue(result.actionable)
        self.assertEqual(
            {item.input_element_id for item in result.matches},
            {"input_1", "input_2"},
        )

    def test_slip_user_id_matches_portal_username(self) -> None:
        store = DocumentFieldStore(
            [
                _document_field("USER ID", FieldSemanticType.ACCESS_CREDENTIAL),
                _document_field("PASSWORD", FieldSemanticType.ACCESS_CREDENTIAL),
            ]
        )

        result = FieldMatcher().match(
            store.descriptors,
            [
                _page_field("input_1", "Username"),
                _page_field("input_2", "Password", html_type=HtmlInputType.PASSWORD),
            ],
        )

        self.assertTrue(result.actionable)
        self.assertTrue(all(item.confidence == ConfidenceLevel.HIGH for item in result.matches))

    def test_ambiguous_identifiers_are_not_guessed(self) -> None:
        store = DocumentFieldStore(
            [
                _document_field("MR No", FieldSemanticType.PATIENT_IDENTIFIER),
                _document_field("Lab No", FieldSemanticType.SAMPLE_IDENTIFIER),
            ]
        )

        result = FieldMatcher().match(
            store.descriptors,
            [_page_field("input_1", "Identifier")],
        )

        self.assertFalse(result.actionable)
        self.assertEqual(result.ambiguous_input_references, ["input_1"])

    def test_missing_date_of_birth_requests_input(self) -> None:
        store = DocumentFieldStore(
            [_document_field("MR No", FieldSemanticType.PATIENT_IDENTIFIER)]
        )

        result = FieldMatcher().match(
            store.descriptors,
            [_page_field("input_1", "Date of Birth", html_type=HtmlInputType.DATE)],
        )

        self.assertFalse(result.actionable)
        self.assertEqual(result.unmatched_required_inputs, ["Date of Birth"])

    def test_user_supplied_field_joins_inventory_by_opaque_reference(self) -> None:
        store = DocumentFieldStore(
            [],
            [UserProvidedField(label="Date of Birth", value="2000-01-02")],
        )

        result = FieldMatcher().match(
            store.descriptors,
            [_page_field("input_1", "Date of Birth", html_type=HtmlInputType.DATE)],
        )

        self.assertTrue(result.actionable)
        self.assertEqual(result.matches[0].document_field_ref, "doc_field_1")
        self.assertNotIn("2000-01-02", result.model_dump_json())

    def test_user_supplied_credential_replaces_same_label_from_slip(self) -> None:
        store = DocumentFieldStore(
            [_document_field("Access Code", FieldSemanticType.ACCESS_CREDENTIAL, "old")],
            [
                UserProvidedField(
                    label="Access Code",
                    value="corrected",
                    semantic_type="access_credential",
                )
            ],
        )

        result = FieldMatcher().match(
            store.descriptors,
            [_page_field("input_1", "Access Code", html_type=HtmlInputType.PASSWORD)],
        )

        self.assertTrue(result.actionable)
        self.assertEqual(len(result.matches), 1)
        self.assertEqual(store.resolve(result.matches[0].document_field_ref), "corrected")


if __name__ == "__main__":
    unittest.main()
