"""Phase 4 orchestration for exactly one controlled browser-related action."""

from collections.abc import Callable

from browser_agent.errors import (
    BrowserAgentError,
    BrowserConfigurationError,
    BrowserLaunchError,
    BrowserTimeoutError,
    NavigationError,
    NonActionablePlanError,
    PageInspectionError,
    SearchExecutionError,
    UnsafeNavigationError,
    UnsafeSearchQueryError,
)
from browser_agent.inspector import PageInspector
from browser_agent.models import BrowserActionResult
from browser_agent.safety import (
    ValidatedURL,
    redact_url_for_display,
    validate_public_url,
)
from browser_agent.search import DuckDuckGoSearchProvider, SearchProvider
from browser_agent.session import BrowserSession, BrowserSessionConfig
from config.settings import Settings
from utils.logger import get_logger
from workflow.models import ActionType, PlanningStatus, WorkflowPlan
from workflow.validation import (
    PlanningValidationError,
    SENSITIVE_FIELD_TYPES,
    validate_search_query,
)


logger = get_logger(__name__)
SessionFactory = Callable[[], BrowserSession]
URLValidator = Callable[[str], ValidatedURL]
ACTIONABLE_STATUSES = {PlanningStatus.READY, PlanningStatus.SEARCH_REQUIRED}


ERROR_CODES: dict[type[BrowserAgentError], str] = {
    BrowserConfigurationError: "browser_configuration_error",
    BrowserLaunchError: "browser_launch_error",
    BrowserTimeoutError: "browser_timeout",
    UnsafeNavigationError: "unsafe_navigation",
    UnsafeSearchQueryError: "unsafe_search_query",
    NavigationError: "navigation_error",
    SearchExecutionError: "search_execution_error",
    PageInspectionError: "page_inspection_error",
    NonActionablePlanError: "non_actionable_plan",
}


class BrowserExecutor:
    """Execute only OPEN_URL or SEARCH_WEB, inspect once, then stop."""

    def __init__(
        self,
        session_factory: SessionFactory,
        *,
        inspector: PageInspector | None = None,
        search_provider: SearchProvider | None = None,
        url_validator: URLValidator = validate_public_url,
    ) -> None:
        self._session_factory = session_factory
        self._inspector = inspector or PageInspector()
        self._search_provider = search_provider or DuckDuckGoSearchProvider()
        self._url_validator = url_validator

    @classmethod
    def from_settings(cls, settings: Settings) -> "BrowserExecutor":
        config = BrowserSessionConfig(
            headless=settings.browser_headless,
            timeout_seconds=settings.browser_timeout_seconds,
            navigation_timeout_seconds=settings.browser_navigation_timeout_seconds,
        )
        return cls(
            lambda: BrowserSession(config),
            search_provider=DuckDuckGoSearchProvider(
                max_results=settings.browser_max_search_results
            ),
        )

    def execute(self, plan: WorkflowPlan) -> BrowserActionResult:
        action = plan.required_next_action
        requested_type = {
            ActionType.OPEN_URL: "url",
            ActionType.SEARCH_WEB: "public_search_query",
        }.get(action.type, "none")
        requested_display = (
            redact_url_for_display(action.target or "")
            if action.type == ActionType.OPEN_URL
            else None
        )
        logger.info("Browser action started: %s", action.type.value.upper())
        try:
            if plan.status not in ACTIONABLE_STATUSES:
                raise NonActionablePlanError(
                    "The workflow plan is not actionable in Phase 4."
                )
            if action.type == ActionType.OPEN_URL:
                return self._execute_open_url(
                    action.target or "", requested_type, requested_display
                )
            if action.type == ActionType.SEARCH_WEB:
                return self._execute_search(plan, action.query or "", requested_type)
            raise NonActionablePlanError(
                "The immediate workflow action is not supported in Phase 4."
            )
        except BrowserAgentError as exc:
            error_code = next(
                (
                    code
                    for error_type, code in ERROR_CODES.items()
                    if isinstance(exc, error_type)
                ),
                "browser_execution_error",
            )
            logger.warning("Browser action failed: %s", error_code)
            return BrowserActionResult(
                action_type=action.type,
                success=False,
                requested_target_type=requested_type,
                requested_target=requested_display,
                final_url=None,
                final_domain=None,
                redirect_occurred=False,
                redirects=[],
                observation=None,
                search_observation=None,
                warnings=[],
                error_type=error_code,
                error_message=str(exc),
            )

    def _execute_open_url(
        self,
        target: str,
        requested_type: str,
        requested_display: str | None,
    ) -> BrowserActionResult:
        self._url_validator(target)
        with self._session_factory() as session:
            navigation = session.open_url(target)
            self._url_validator(navigation.final.url)
            observation = self._inspector.inspect(session.page)
            warnings = list(
                dict.fromkeys([*navigation.warnings, *observation.warnings])
            )
            return BrowserActionResult(
                action_type=ActionType.OPEN_URL,
                success=True,
                requested_target_type=requested_type,
                requested_target=requested_display,
                final_url=observation.final_url,
                final_domain=observation.final_domain,
                redirect_occurred=bool(navigation.redirects),
                redirects=navigation.redirects,
                observation=observation,
                search_observation=None,
                warnings=warnings,
                error_type=None,
                error_message=None,
            )

    def _execute_search(
        self, plan: WorkflowPlan, query: str, requested_type: str
    ) -> BrowserActionResult:
        sensitive_values = [
            field.value
            for field in plan.available_fields
            if field.semantic_type in SENSITIVE_FIELD_TYPES
        ]
        try:
            validate_search_query(query, sensitive_values)
        except PlanningValidationError as exc:
            raise UnsafeSearchQueryError(
                "The planned search contains sensitive document information."
            ) from exc

        with self._session_factory() as session:
            search_observation = self._search_provider.search(session, query)
            observation = self._inspector.inspect(session.page)
            navigation = session.last_navigation
            redirects = navigation.redirects if navigation else []
            navigation_warnings = navigation.warnings if navigation else []
            warnings = list(
                dict.fromkeys(
                    [
                        *navigation_warnings,
                        *search_observation.warnings,
                        *observation.warnings,
                    ]
                )
            )
            return BrowserActionResult(
                action_type=ActionType.SEARCH_WEB,
                success=True,
                requested_target_type=requested_type,
                requested_target=None,
                final_url=observation.final_url,
                final_domain=observation.final_domain,
                redirect_occurred=bool(redirects),
                redirects=redirects,
                observation=observation,
                search_observation=search_observation,
                warnings=warnings,
                error_type=None,
                error_message=None,
            )
