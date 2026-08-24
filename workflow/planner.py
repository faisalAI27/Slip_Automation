"""Main deterministic orchestration for Phase 3 dynamic workflow planning."""

from document_understanding.models import (
    AnalysisStatus,
    ConfidenceLevel,
    DocumentUnderstandingResult,
    URLPurpose,
)
from utils.logger import get_logger
from workflow.models import (
    ActionType,
    AvailableField,
    NextAction,
    PlannedOrganization,
    PlanningStatus,
    PortalCandidate,
    PortalSource,
    PortalStrategy,
    UserInputRequirement,
    WorkflowPlan,
)
from workflow.rules import (
    build_available_fields,
    build_portal_candidates,
    has_low_confidence_context,
    known_organization,
    safe_search_query,
    select_portal_candidate,
)
from workflow.validation import (
    PlanningValidationError,
    sensitive_values,
    validate_plan,
    validate_search_query,
    normalize_navigation_url,
)


logger = get_logger(__name__)
DEFAULT_REPORT_RETRIEVAL_GOAL = (
    "Retrieve and download the medical or laboratory report associated with the "
    "uploaded document."
)


class WorkflowPlanner:
    def __init__(self, goal: str = DEFAULT_REPORT_RETRIEVAL_GOAL) -> None:
        self._goal = goal.strip()
        if not self._goal:
            raise ValueError("Workflow goal cannot be empty.")

    def plan(self, result: DocumentUnderstandingResult) -> WorkflowPlan:
        logger.info("Workflow planning started")
        plan = self._build_plan(result)
        validated = validate_plan(plan, result)
        logger.info("Portal strategy selected: %s", validated.portal_strategy.value)
        logger.info("Planning completed: %s", validated.status.value.upper())
        logger.info("Next action type: %s", validated.required_next_action.type.value.upper())
        return validated

    def plan_user_provided_url(
        self, result: DocumentUnderstandingResult, value: str
    ) -> WorkflowPlan:
        """Create one validated OPEN_URL action after automatic discovery stops."""
        normalized = normalize_navigation_url(value)
        if normalized is None:
            raise PlanningValidationError(
                "Enter a public website such as https://hospital.example."
            )
        candidate = PortalCandidate(
            url=normalized,
            source=PortalSource.USER_PROVIDED_URL,
            likely_purpose=URLPurpose.UNKNOWN,
            confidence=ConfidenceLevel.MEDIUM,
            reason="The user supplied this website after automatic discovery stopped.",
        )
        plan = WorkflowPlan(
            goal=self._goal,
            status=PlanningStatus.READY,
            organization=known_organization(result),
            portal_strategy=PortalStrategy.USER_PROVIDED_URL,
            portal_candidates=[candidate],
            available_fields=build_available_fields(result),
            required_next_action=NextAction(
                type=ActionType.OPEN_URL,
                target=normalized,
                reason=candidate.reason,
                confidence=ConfidenceLevel.MEDIUM,
            ),
            user_input_requirement=UserInputRequirement(
                required=False, reason=None, requested_information=[]
            ),
            warnings=list(
                dict.fromkeys(
                    [
                        *result.warnings,
                        "Automatic portal discovery stopped; a user-provided public website is being checked.",
                    ]
                )
            ),
            planner_summary=(
                "A user-provided public website is ready for one safe, observation-only check."
            ),
        )
        return validate_plan(plan, result)

    def _build_plan(self, result: DocumentUnderstandingResult) -> WorkflowPlan:
        organization = known_organization(result)
        available_fields = build_available_fields(result)
        candidates, candidate_warnings = build_portal_candidates(result)
        warnings = list(dict.fromkeys([*result.warnings, *candidate_warnings]))

        if result.analysis_status == AnalysisStatus.NOT_MEDICAL:
            return self._stop_plan(
                status=PlanningStatus.UNSUPPORTED,
                strategy=PortalStrategy.UNSUPPORTED,
                organization=organization,
                candidates=candidates,
                available_fields=available_fields,
                warnings=warnings,
                reason="The document is not suitable for medical report retrieval.",
                summary="Planning stopped because the document is not a supported medical document.",
            )

        if result.analysis_status in {AnalysisStatus.UNCLEAR, AnalysisStatus.UNKNOWN}:
            warnings.append("Document understanding is too uncertain for safe continuation.")
            return self._user_input_plan(
                organization=organization,
                candidates=candidates,
                available_fields=available_fields,
                warnings=list(dict.fromkeys(warnings)),
                reason="The document could not be understood reliably enough to continue.",
                requested_information=["A clearer or more complete medical document"],
            )

        selected = select_portal_candidate(candidates)
        if selected is not None:
            strategy = {
                PortalSource.PRINTED_URL: PortalStrategy.EXPLICIT_REPORT_URL,
                PortalSource.QR_CODE: PortalStrategy.QR_REPORT_URL,
                PortalSource.ORGANIZATION_HOMEPAGE: PortalStrategy.ORGANIZATION_HOMEPAGE,
                PortalSource.USER_PROVIDED_URL: PortalStrategy.USER_PROVIDED_URL,
                PortalSource.FUTURE_WEB_SEARCH: PortalStrategy.WEB_SEARCH,
            }[selected.source]
            if has_low_confidence_context(result):
                warnings.append(
                    "Some document context has low confidence; verify important values before execution."
                )
            return WorkflowPlan(
                goal=self._goal,
                status=PlanningStatus.READY,
                organization=organization,
                portal_strategy=strategy,
                portal_candidates=candidates,
                available_fields=available_fields,
                required_next_action=NextAction(
                    type=ActionType.OPEN_URL,
                    target=selected.url,
                    reason=selected.reason,
                    confidence=selected.confidence,
                ),
                user_input_requirement=UserInputRequirement(
                    required=False, reason=None, requested_information=[]
                ),
                warnings=list(dict.fromkeys(warnings)),
                planner_summary=(
                    "A portal candidate is available; the future browser phase should "
                    "open it first without submitting any information."
                ),
            )

        if organization is not None:
            if has_low_confidence_context(result):
                warnings.append(
                    "The organization identification is too uncertain for a safe web search."
                )
                return self._user_input_plan(
                    organization=organization,
                    candidates=candidates,
                    available_fields=available_fields,
                    warnings=list(dict.fromkeys(warnings)),
                    reason="The organization needs confirmation before portal discovery.",
                    requested_information=["Confirmed organization name"],
                )

            query = safe_search_query(organization)
            # Validate before creating the plan so a misclassified organization name
            # cannot leak a patient value into a future search instruction.
            try:
                validate_search_query(query, sensitive_values(result))
            except PlanningValidationError:
                warnings.append(
                    "A safe organization-only search query could not be generated."
                )
                return self._user_input_plan(
                    organization=organization,
                    candidates=candidates,
                    available_fields=available_fields,
                    warnings=list(dict.fromkeys(warnings)),
                    reason="The organization name must be confirmed before portal discovery.",
                    requested_information=["Confirmed organization name"],
                )

            return WorkflowPlan(
                goal=self._goal,
                status=PlanningStatus.SEARCH_REQUIRED,
                organization=organization,
                portal_strategy=PortalStrategy.WEB_SEARCH,
                portal_candidates=candidates,
                available_fields=available_fields,
                required_next_action=NextAction(
                    type=ActionType.SEARCH_WEB,
                    query=query,
                    reason=(
                        "No usable portal URL was found, so a public organization-only "
                        "search is required."
                    ),
                    confidence=organization.confidence,
                ),
                user_input_requirement=UserInputRequirement(
                    required=False, reason=None, requested_information=[]
                ),
                warnings=warnings,
                planner_summary=(
                    "No usable portal URL was found; an organization-only web search is "
                    "the next planned step."
                ),
            )

        return self._user_input_plan(
            organization=None,
            candidates=candidates,
            available_fields=available_fields,
            warnings=warnings,
            reason="No organization or usable portal URL could be identified.",
            requested_information=["Organization name or a clearer document"],
        )

    def _user_input_plan(
        self,
        *,
        organization: PlannedOrganization | None,
        candidates: list[PortalCandidate],
        available_fields: list[AvailableField],
        warnings: list[str],
        reason: str,
        requested_information: list[str],
    ) -> WorkflowPlan:
        return WorkflowPlan(
            goal=self._goal,
            status=PlanningStatus.USER_INPUT_REQUIRED,
            organization=organization,
            portal_strategy=PortalStrategy.USER_INPUT_REQUIRED,
            portal_candidates=candidates,
            available_fields=available_fields,
            required_next_action=NextAction(
                type=ActionType.STOP,
                reason=reason,
                confidence=(
                    organization.confidence if organization else ConfidenceLevel.UNKNOWN
                ),
            ),
            user_input_requirement=UserInputRequirement(
                required=True,
                reason=reason,
                requested_information=requested_information,
            ),
            warnings=warnings,
            planner_summary="Planning paused because more reliable public information is required.",
        )

    def _stop_plan(
        self,
        *,
        status: PlanningStatus,
        strategy: PortalStrategy,
        organization: PlannedOrganization | None,
        candidates: list[PortalCandidate],
        available_fields: list[AvailableField],
        warnings: list[str],
        reason: str,
        summary: str,
    ) -> WorkflowPlan:
        return WorkflowPlan(
            goal=self._goal,
            status=status,
            organization=organization,
            portal_strategy=strategy,
            portal_candidates=candidates,
            available_fields=available_fields,
            required_next_action=NextAction(
                type=ActionType.STOP,
                reason=reason,
                confidence=ConfidenceLevel.HIGH,
            ),
            user_input_requirement=UserInputRequirement(
                required=False, reason=None, requested_information=[]
            ),
            warnings=warnings,
            planner_summary=summary,
        )
