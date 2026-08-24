import unittest
from unittest.mock import patch

from browser_agent.errors import InteractionSafetyError
from browser_agent.field_matcher import DocumentFieldStore
from browser_agent.interaction import InteractionSafetyValidator
from browser_agent.models import (
    AgentAction,
    AgentActionType,
    AuthenticationSignals,
    BrowserObservation,
    FormObservation,
    HtmlInputType,
    InputFieldObservation,
    PageType,
    VerificationSignals,
)
from browser_agent.safety import ValidatedURL
from document_understanding.models import ConfidenceLevel, FieldSemanticType
from workflow.models import AvailableField, InformationSource, PotentialUse


def _store() -> DocumentFieldStore:
    return DocumentFieldStore(
        [
            AvailableField(
                label="MR Number",
                value="PRIVATE-VALUE",
                semantic_type=FieldSemanticType.PATIENT_IDENTIFIER,
                source=InformationSource.DOCUMENT_FIELD,
                potential_use=PotentialUse.PORTAL_AUTHENTICATION,
                confidence=ConfidenceLevel.HIGH,
            )
        ]
    )


def _observation(*, form_domain: str | None = None) -> BrowserObservation:
    return BrowserObservation(
        final_url="https://reports.example.test/login",
        final_domain="example.test",
        page_title="Login",
        page_type=PageType.REPORT_LOGIN_PAGE,
        visible_text_summary="Login",
        forms=[
            FormObservation(
                element_id="form_1",
                name="login",
                method="post",
                action_domain=form_domain,
                input_references=["input_1"],
            )
        ],
        input_fields=[
            InputFieldObservation(
                element_id="input_1",
                html_type=HtmlInputType.TEXT,
                name="patient",
                label="Patient Number",
                placeholder=None,
                aria_label=None,
                required=True,
                disabled=False,
                readonly=False,
                autocomplete=None,
            )
        ],
        buttons=[],
        links=[],
        download_candidates=[],
        authentication_signals=AuthenticationSignals(
            authentication_required=True,
            field_count=1,
            confidence=ConfidenceLevel.HIGH,
        ),
        verification_signals=VerificationSignals(
            otp_detected=False,
            captcha_detected=False,
            email_verification_detected=False,
            verification_required=False,
        ),
        errors_or_messages=[],
        warnings=[],
    )


def _fill(ref: str = "input_1") -> AgentAction:
    return AgentAction(
        type=AgentActionType.FILL_FIELD,
        element_id=ref,
        document_field_ref="doc_field_1",
        reason="Validated semantic mapping.",
        confidence=ConfidenceLevel.HIGH,
    )


def _validated(scheme: str, domain: str = "example.test") -> ValidatedURL:
    return ValidatedURL(
        url=f"{scheme}://reports.{domain}/login",
        scheme=scheme,
        hostname=f"reports.{domain}",
        port=443 if scheme == "https" else 80,
        domain=domain,
    )


class InteractionSafetyTests(unittest.TestCase):
    def test_sensitive_field_is_blocked_on_http(self) -> None:
        validator = InteractionSafetyValidator(_store())
        with (
            patch(
                "browser_agent.interaction.validate_public_url",
                return_value=_validated("http"),
            ),
            self.assertRaises(InteractionSafetyError),
        ):
            validator.validate_fill(
                _fill(),
                _observation(),
                current_url="http://reports.example.test/login",
                trusted_domains={"example.test"},
            )

    def test_unknown_cross_domain_form_destination_is_blocked(self) -> None:
        validator = InteractionSafetyValidator(_store())
        with (
            patch(
                "browser_agent.interaction.validate_public_url",
                return_value=_validated("https"),
            ),
            self.assertRaises(InteractionSafetyError),
        ):
            validator.validate_fill(
                _fill(),
                _observation(form_domain="untrusted.test"),
                current_url="https://reports.example.test/login",
                trusted_domains={"example.test"},
            )

    def test_hallucinated_input_reference_is_rejected(self) -> None:
        validator = InteractionSafetyValidator(_store())
        with self.assertRaises(InteractionSafetyError):
            validator.validate_fill(
                _fill("input_99"),
                _observation(),
                current_url="https://reports.example.test/login",
                trusted_domains={"example.test"},
            )


if __name__ == "__main__":
    unittest.main()
