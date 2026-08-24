import unittest

from browser_agent.errors import BrowserLaunchError
from browser_agent.executor import BrowserExecutor
from browser_agent.models import (
    AuthenticationSignals,
    BrowserObservation,
    PageType,
    SearchObservation,
    SearchResult,
    VerificationSignals,
)
from browser_agent.safety import ValidatedURL, validate_public_url
from browser_agent.session import NavigationOutcome
from browser_agent.tools import BrowserToolName, PHASE4_EXECUTABLE_TOOLS
from document_understanding.models import ConfidenceLevel, DocumentUnderstandingResult
from workflow.models import ActionType
from workflow.planner import WorkflowPlanner


def _payload() -> dict[str, object]:
    return {
        "analysis_status": "usable",
        "document_type": "laboratory slip",
        "document_type_confidence": "high",
        "organization": {
            "name": "Example Diagnostics",
            "type": "diagnostic_center",
            "confidence": "high",
        },
        "purpose": "retrieve report",
        "likely_action": "view report online",
        "urls": [
            {
                "url": "https://example.test/reports",
                "normalized_url": "https://example.test/reports",
                "context": "Reports",
                "likely_purpose": "report_portal",
                "confidence": "high",
            }
        ],
        "qr_codes": [],
        "fields": [
            {
                "label": "MR Number",
                "value": "MR-123456",
                "semantic_type": "patient_identifier",
                "confidence": "high",
            },
            {
                "label": "Access Code",
                "value": "88219",
                "semantic_type": "access_credential",
                "confidence": "high",
            },
        ],
        "dates": [],
        "instructions": [],
        "raw_summary": "Laboratory slip",
        "overall_confidence": "high",
        "warnings": [],
    }


def _plan(*, include_url: bool = True, not_medical: bool = False):
    payload = _payload()
    if not include_url:
        payload["urls"] = []
    if not_medical:
        payload["analysis_status"] = "not_medical"
    result = DocumentUnderstandingResult.model_validate(payload)
    return WorkflowPlanner().plan(result)


def _validated(value: str) -> ValidatedURL:
    return validate_public_url(
        value,
        resolver=lambda _host, _port: ["93.184.216.34"],
    )


def _observation(
    final_url: str = "https://example.test/reports",
) -> BrowserObservation:
    return BrowserObservation(
        final_url=final_url,
        final_domain="example.test",
        page_title="Online Reports",
        page_type=PageType.REPORT_LOGIN_PAGE,
        visible_text_summary="Online reports",
        forms=[],
        input_fields=[],
        buttons=[],
        links=[],
        download_candidates=[],
        authentication_signals=AuthenticationSignals(
            authentication_required=False,
            field_count=0,
            confidence=ConfidenceLevel.LOW,
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


class FakeInspector:
    def __init__(self, observation: BrowserObservation | None = None) -> None:
        self.observation = observation or _observation()

    def inspect(self, _page: object) -> BrowserObservation:
        return self.observation


class FakeSession:
    def __init__(
        self,
        *,
        final_url: str = "https://example.test/reports",
        enter_error: Exception | None = None,
    ) -> None:
        self.page = object()
        self.closed = False
        self.enter_error = enter_error
        requested = _validated("https://example.test/reports")
        final = (
            ValidatedURL(
                url=final_url,
                scheme="http",
                hostname="127.0.0.1",
                port=80,
                domain="127.0.0.1",
            )
            if "127.0.0.1" in final_url
            else _validated(final_url)
        )
        self.last_navigation = NavigationOutcome(
            requested=requested,
            final=final,
            redirects=[],
            status_code=200,
            warnings=[],
        )

    def __enter__(self):
        if self.enter_error:
            raise self.enter_error
        return self

    def __exit__(self, *_: object) -> None:
        self.closed = True

    def open_url(self, _target: str) -> NavigationOutcome:
        return self.last_navigation


class FakeSearchProvider:
    def search(self, _session: FakeSession, query: str) -> SearchObservation:
        return SearchObservation(
            query=query,
            provider="mock_search",
            results=[
                SearchResult(
                    title="Example Diagnostics reports",
                    url="https://example.test/reports",
                    domain="example.test",
                    snippet="Official report portal",
                    position=1,
                )
            ],
            warnings=[],
        )


class BrowserExecutorTests(unittest.TestCase):
    def test_phase_four_tool_allowlist_excludes_interactive_actions(self) -> None:
        self.assertEqual(
            PHASE4_EXECUTABLE_TOOLS,
            {
                BrowserToolName.OPEN_URL,
                BrowserToolName.SEARCH_WEB,
                BrowserToolName.INSPECT_PAGE,
            },
        )
        self.assertNotIn(BrowserToolName.FILL_FIELD, PHASE4_EXECUTABLE_TOOLS)
        self.assertNotIn(BrowserToolName.CLICK, PHASE4_EXECUTABLE_TOOLS)
        self.assertNotIn(BrowserToolName.DOWNLOAD, PHASE4_EXECUTABLE_TOOLS)

    def test_safe_open_url_returns_observation_and_closes_session(self) -> None:
        session = FakeSession()
        executor = BrowserExecutor(
            lambda: session,
            inspector=FakeInspector(),
            url_validator=_validated,
        )

        result = executor.execute(_plan())

        self.assertTrue(result.success)
        self.assertEqual(result.action_type, ActionType.OPEN_URL)
        self.assertIsNotNone(result.observation)
        self.assertTrue(session.closed)

    def test_unsafe_scheme_is_blocked_before_session_creation(self) -> None:
        plan = _plan()
        unsafe_action = plan.required_next_action.model_copy(
            update={"target": "javascript:alert(1)"}
        )
        plan = plan.model_copy(update={"required_next_action": unsafe_action})
        created = False

        def factory():
            nonlocal created
            created = True
            return FakeSession()

        result = BrowserExecutor(factory, url_validator=_validated).execute(plan)

        self.assertFalse(result.success)
        self.assertEqual(result.error_type, "unsafe_navigation")
        self.assertFalse(created)

    def test_unsafe_redirect_destination_is_rejected(self) -> None:
        session = FakeSession(final_url="http://127.0.0.1/private")
        executor = BrowserExecutor(
            lambda: session,
            inspector=FakeInspector(),
            url_validator=_validated,
        )

        result = executor.execute(_plan())

        self.assertFalse(result.success)
        self.assertEqual(result.error_type, "unsafe_navigation")
        self.assertTrue(session.closed)

    def test_safe_search_returns_structured_results(self) -> None:
        session = FakeSession(final_url="https://html.duckduckgo.com/html/")
        search_observation = _observation("https://html.duckduckgo.com/html/")
        executor = BrowserExecutor(
            lambda: session,
            inspector=FakeInspector(search_observation),
            search_provider=FakeSearchProvider(),
            url_validator=_validated,
        )

        result = executor.execute(_plan(include_url=False))

        self.assertTrue(result.success)
        self.assertEqual(result.action_type, ActionType.SEARCH_WEB)
        self.assertEqual(len(result.search_observation.results), 1)  # type: ignore[union-attr]
        self.assertTrue(session.closed)

    def test_sensitive_search_is_refused_before_browser_launch(self) -> None:
        plan = _plan(include_url=False)
        unsafe_action = plan.required_next_action.model_copy(
            update={"query": "Example Diagnostics MR-123456 88219 reports"}
        )
        plan = plan.model_copy(update={"required_next_action": unsafe_action})
        created = False

        def factory():
            nonlocal created
            created = True
            return FakeSession()

        with self.assertLogs("browser_agent.executor", level="INFO") as captured:
            result = BrowserExecutor(factory, url_validator=_validated).execute(plan)

        self.assertFalse(result.success)
        self.assertEqual(result.error_type, "unsafe_search_query")
        self.assertFalse(created)
        self.assertNotIn("MR-123456", result.model_dump_json())
        self.assertNotIn("88219", result.model_dump_json())
        logs = " ".join(captured.output)
        self.assertNotIn("MR-123456", logs)
        self.assertNotIn("88219", logs)

    def test_unsupported_plan_never_launches_browser(self) -> None:
        created = False

        def factory():
            nonlocal created
            created = True
            return FakeSession()

        result = BrowserExecutor(factory, url_validator=_validated).execute(
            _plan(not_medical=True)
        )

        self.assertFalse(result.success)
        self.assertEqual(result.error_type, "non_actionable_plan")
        self.assertFalse(created)

    def test_browser_launch_failure_is_controlled(self) -> None:
        session = FakeSession(
            enter_error=BrowserLaunchError("Chromium could not be launched.")
        )
        result = BrowserExecutor(
            lambda: session,
            inspector=FakeInspector(),
            url_validator=_validated,
        ).execute(_plan())

        self.assertFalse(result.success)
        self.assertEqual(result.error_type, "browser_launch_error")
        self.assertNotIn("MR-123456", result.error_message or "")


if __name__ == "__main__":
    unittest.main()
