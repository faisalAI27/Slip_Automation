"""Bounded observe-decide-validate-act retrieval orchestration for Phase 5."""

from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlsplit

from browser_agent.download_manager import ReportDownloadManager
from browser_agent.errors import BrowserAgentError, InteractionSafetyError
from browser_agent.field_matcher import DocumentFieldStore, FieldMatcher
from browser_agent.interaction import (
    ControlledBrowserTools,
    RetrievalToolset,
    SearchSelection,
    SearchResultRanker,
)
from browser_agent.models import (
    AgentAction,
    AgentActionType,
    BrowserObservation,
    ButtonObservation,
    ButtonSemanticAction,
    ConfidenceLevel,
    DownloadCandidate,
    FieldMatch,
    LinkObservation,
    LinkPurpose,
    PageType,
    RetrievalChoice,
    RetrievalResult,
    RetrievalStatus,
    RetrievalUserInputRequirement,
    SafeActionRecord,
    SearchObservation,
    UserProvidedField,
)
from browser_agent.search import DuckDuckGoSearchProvider
from browser_agent.session import BrowserSession, BrowserSessionConfig
from config.settings import Settings
from document_understanding.models import DocumentUnderstandingResult
from utils.logger import get_logger
from workflow.models import ActionType, PlanningStatus, WorkflowPlan
from workflow.validation import PlanningValidationError, validate_search_query


logger = get_logger(__name__)
ToolFactory = Callable[[DocumentFieldStore], RetrievalToolset]
INVALID_CREDENTIAL_TERMS = {
    "authentication failed",
    "incorrect password",
    "invalid code",
    "invalid credential",
    "invalid id",
}
REPORT_NOT_FOUND_TERMS = {
    "no report available",
    "no reports available",
    "no result found",
    "report not found",
}


@dataclass(frozen=True, slots=True)
class RetrievalAgentConfig:
    max_steps: int = 12
    max_navigations: int = 6
    max_form_submissions: int = 2
    max_wait_seconds: float = 8.0


class RetrievalAgent:
    def __init__(
        self,
        tool_factory: ToolFactory,
        *,
        config: RetrievalAgentConfig | None = None,
        field_matcher: FieldMatcher | None = None,
        search_ranker: SearchResultRanker | None = None,
        portal_url_overrides: dict[str, str] | None = None,
    ) -> None:
        self._tool_factory = tool_factory
        self._config = config or RetrievalAgentConfig()
        self._field_matcher = field_matcher or FieldMatcher()
        self._search_ranker = search_ranker or SearchResultRanker()
        self._portal_url_overrides = {
            host.casefold(): url for host, url in (portal_url_overrides or {}).items()
        }

    @classmethod
    def from_settings(cls, settings: Settings) -> "RetrievalAgent":
        session_config = BrowserSessionConfig(
            headless=settings.browser_headless,
            timeout_seconds=settings.browser_timeout_seconds,
            navigation_timeout_seconds=settings.browser_navigation_timeout_seconds,
        )

        def create_tools(field_store: DocumentFieldStore) -> ControlledBrowserTools:
            return ControlledBrowserTools(
                BrowserSession(session_config),
                field_store,
                ReportDownloadManager(
                    settings.temp_dir,
                    max_download_mb=settings.max_report_download_mb,
                ),
                search_provider=DuckDuckGoSearchProvider(
                    max_results=settings.browser_max_search_results
                ),
            )

        return cls(
            create_tools,
            config=RetrievalAgentConfig(
                max_steps=settings.agent_max_steps,
                max_navigations=settings.agent_max_navigations,
                max_form_submissions=settings.agent_max_form_submissions,
                max_wait_seconds=settings.agent_max_wait_seconds,
            ),
            portal_url_overrides=settings.portal_url_overrides,
        )

    def run(
        self,
        document_result: DocumentUnderstandingResult,
        workflow_plan: WorkflowPlan,
        *,
        user_fields: list[UserProvidedField] | None = None,
        selected_choice: str | None = None,
    ) -> RetrievalResult:
        logger.info("Retrieval agent started")
        field_store = DocumentFieldStore(workflow_plan.available_fields, user_fields)
        history: list[SafeActionRecord] = []
        mappings: list[FieldMatch] = []
        steps = 0
        navigations = 0
        authentication_submissions = 0
        post_authentication_waits = 0
        filled_inputs: set[str] = set()
        loop_counts: dict[tuple[str, str | None, str | None, str | None], int] = {}
        observation: BrowserObservation | None = None

        if workflow_plan.status not in {
            PlanningStatus.READY,
            PlanningStatus.SEARCH_REQUIRED,
        }:
            status = (
                RetrievalStatus.UNSUPPORTED
                if workflow_plan.status == PlanningStatus.UNSUPPORTED
                else RetrievalStatus.USER_INPUT_REQUIRED
            )
            return self._result(
                status,
                observation=None,
                tools=None,
                steps=0,
                history=[],
                mappings=[],
                reason="The retrieval plan is not ready for browser interaction.",
                requested=["A supported document or confirmed report website"],
            )

        try:
            with self._tool_factory(field_store) as tools:
                initial = workflow_plan.required_next_action
                if initial.type == ActionType.OPEN_URL:
                    target = self._portal_target(initial.target or "")
                    action = AgentAction(
                        type=AgentActionType.OPEN_URL,
                        reason="Open the validated portal selected by the workflow plan.",
                        confidence=initial.confidence,
                    )
                    observation = tools.open_url(target)
                    steps += 1
                    navigations += 1
                    self._record(history, steps, action, tools.current_domain)
                elif initial.type == ActionType.SEARCH_WEB:
                    query = initial.query or ""
                    validate_search_query(
                        query,
                        [field.value for field in workflow_plan.available_fields],
                    )
                    action = AgentAction(
                        type=AgentActionType.SEARCH_WEB,
                        reason="Run the validated organization-only public search.",
                        confidence=initial.confidence,
                    )
                    search = tools.search_web(query)
                    steps += 1
                    navigations += 1
                    self._record(history, steps, action, tools.current_domain)
                    selected = self._select_search_result(
                        workflow_plan, search, selected_choice=selected_choice
                    )
                    if selected.result is None:
                        if selected.ambiguous:
                            return self._result(
                                RetrievalStatus.AMBIGUOUS,
                                observation=None,
                                tools=tools,
                                steps=steps,
                                history=history,
                                mappings=mappings,
                                reason="More than one possible report website was found.",
                                choices=[
                                    RetrievalChoice(
                                        label=f"{item.title} · {item.domain}",
                                        value=item.url,
                                    )
                                    for item in search.results[:5]
                                ],
                            )
                        return self._result(
                            RetrievalStatus.REPORT_NOT_FOUND,
                            observation=None,
                            tools=tools,
                            steps=steps,
                            history=history,
                            mappings=mappings,
                            reason="No strong official report-service result was found.",
                        )
                    if navigations >= self._config.max_navigations:
                        return self._limit_result(
                            observation, tools, steps, history, mappings, "navigation"
                        )
                    open_action = AgentAction(
                        type=AgentActionType.OPEN_SEARCH_RESULT,
                        search_result_position=selected.result.position,
                        reason="Open the single strongest official-looking report result.",
                        confidence=ConfidenceLevel.HIGH,
                    )
                    observation = tools.open_search_result(selected.result)
                    steps += 1
                    navigations += 1
                    self._record(history, steps, open_action, tools.current_domain)
                else:
                    return self._result(
                        RetrievalStatus.UNSUPPORTED,
                        observation=None,
                        tools=tools,
                        steps=steps,
                        history=history,
                        mappings=mappings,
                        reason="The initial workflow action is not supported.",
                    )

                while observation is not None and steps < self._config.max_steps:
                    if observation.verification_signals.verification_required:
                        return self._result(
                            RetrievalStatus.VERIFICATION_REQUIRED,
                            observation=observation,
                            tools=tools,
                            steps=steps,
                            history=history,
                            mappings=mappings,
                            reason="The report website requires manual verification.",
                        )
                    if self._contains_message(observation, REPORT_NOT_FOUND_TERMS):
                        return self._result(
                            RetrievalStatus.REPORT_NOT_FOUND,
                            observation=observation,
                            tools=tools,
                            steps=steps,
                            history=history,
                            mappings=mappings,
                            reason="The report service did not show an available report.",
                        )
                    if authentication_submissions and self._contains_message(
                        observation, INVALID_CREDENTIAL_TERMS
                    ):
                        return self._result(
                            RetrievalStatus.USER_INPUT_REQUIRED,
                            observation=observation,
                            tools=tools,
                            steps=steps,
                            history=history,
                            mappings=mappings,
                            reason="The report service rejected the information from the slip.",
                            requested=list(
                                dict.fromkeys(
                                    item.page_field_label
                                    or item.document_label
                                    or "Report-access information"
                                    for item in mappings
                                )
                            )
                            or ["Correct report-access details"],
                        )

                    if observation.authentication_signals.authentication_required:
                        mapping = self._field_matcher.match(
                            field_store.descriptors,
                            observation.input_fields,
                        )
                        mappings = self._merge_mappings(mappings, mapping.matches)
                        if mapping.ambiguous_input_references:
                            return self._result(
                                RetrievalStatus.AMBIGUOUS,
                                observation=observation,
                                tools=tools,
                                steps=steps,
                                history=history,
                                mappings=mappings,
                                reason="The website fields could not be matched confidently.",
                                requested=["Confirm the report-access fields"],
                            )
                        if mapping.unmatched_required_inputs:
                            return self._result(
                                RetrievalStatus.USER_INPUT_REQUIRED,
                                observation=observation,
                                tools=tools,
                                steps=steps,
                                history=history,
                                mappings=mappings,
                                reason="The report website needs information not found on the slip.",
                                requested=mapping.unmatched_required_inputs,
                            )
                        low_confidence = [
                            item
                            for item in mapping.matches
                            if item.confidence != ConfidenceLevel.HIGH
                        ]
                        if low_confidence or not mapping.matches:
                            return self._result(
                                RetrievalStatus.USER_INPUT_REQUIRED,
                                observation=observation,
                                tools=tools,
                                steps=steps,
                                history=history,
                                mappings=mappings,
                                reason="The website fields need confirmation before submission.",
                                requested=[
                                    item.page_field_label or "Report website field"
                                    for item in low_confidence
                                ]
                                or ["Report-access information"],
                            )

                        pending = [
                            item
                            for item in mapping.matches
                            if item.input_element_id not in filled_inputs
                        ]
                        if pending:
                            match = pending[0]
                            fill_action = AgentAction(
                                type=AgentActionType.FILL_FIELD,
                                element_id=match.input_element_id,
                                document_field_ref=match.document_field_ref,
                                reason="Fill a high-confidence semantic field match.",
                                confidence=match.confidence,
                            )
                            if self._looped(loop_counts, fill_action, observation, tools):
                                return self._loop_result(
                                    observation, tools, steps, history, mappings
                                )
                            tools.fill_field(fill_action, observation)
                            steps += 1
                            filled_inputs.add(match.input_element_id)
                            self._record(
                                history,
                                steps,
                                fill_action,
                                tools.current_domain,
                                semantic_type=match.document_semantic_type,
                            )
                            continue

                        submit = self._submit_button(
                            observation,
                            {item.input_element_id for item in mapping.matches},
                        )
                        if submit is None:
                            return self._result(
                                RetrievalStatus.AMBIGUOUS,
                                observation=observation,
                                tools=tools,
                                steps=steps,
                                history=history,
                                mappings=mappings,
                                reason="A safe report-access button could not be identified.",
                                requested=["Choose the report-access button"],
                            )
                        if authentication_submissions >= 1 or (
                            authentication_submissions
                            >= self._config.max_form_submissions
                        ):
                            return self._result(
                                RetrievalStatus.USER_INPUT_REQUIRED,
                                observation=observation,
                                tools=tools,
                                steps=steps,
                                history=history,
                                mappings=mappings,
                                reason="The single automatic authentication attempt was used.",
                                requested=["Check the report-access details"],
                            )
                        if navigations >= self._config.max_navigations:
                            return self._limit_result(
                                observation,
                                tools,
                                steps,
                                history,
                                mappings,
                                "navigation",
                            )
                        click_action = AgentAction(
                            type=AgentActionType.CLICK,
                            element_id=submit.element_id,
                            reason="Submit the matched report-access fields once.",
                            confidence=ConfidenceLevel.HIGH,
                        )
                        if self._looped(loop_counts, click_action, observation, tools):
                            return self._loop_result(
                                observation, tools, steps, history, mappings
                            )
                        steps += 1
                        authentication_submissions += 1
                        navigations += 1
                        self._record(
                            history,
                            steps,
                            click_action,
                            tools.current_domain,
                            outcome="attempted",
                        )
                        observation = tools.click(click_action, observation)
                        history[-1] = history[-1].model_copy(
                            update={"outcome": "completed"}
                        )
                        filled_inputs.clear()
                        continue

                    download, download_ambiguous = self._download_candidate(
                        observation, selected_choice=selected_choice
                    )
                    if download_ambiguous:
                        return self._result(
                            RetrievalStatus.AMBIGUOUS,
                            observation=observation,
                            tools=tools,
                            steps=steps,
                            history=history,
                            mappings=mappings,
                            reason="Several report downloads were found and none was clearly preferred.",
                            choices=[
                                RetrievalChoice(label=item.label, value=item.element_id)
                                for item in observation.download_candidates
                            ],
                        )
                    if download is not None:
                        action = AgentAction(
                            type=AgentActionType.DOWNLOAD,
                            element_id=download.element_id,
                            reason="Download the single validated PDF report candidate.",
                            confidence=download.confidence,
                        )
                        if self._looped(loop_counts, action, observation, tools):
                            return self._loop_result(
                                observation, tools, steps, history, mappings
                            )
                        downloaded = tools.download(action, observation)
                        steps += 1
                        self._record(history, steps, action, tools.current_domain)
                        logger.info("Retrieval agent completed")
                        return RetrievalResult(
                            status=RetrievalStatus.DOWNLOADED,
                            downloaded_file=downloaded,
                            final_page_type=observation.page_type,
                            current_domain=tools.current_domain,
                            steps_completed=steps,
                            user_input_requirement=RetrievalUserInputRequirement(
                                required=False,
                                reason=None,
                                requested_information=[],
                            ),
                            warnings=tools.warnings,
                            failure_reason=None,
                            safe_action_history=history,
                            field_mappings=mappings,
                        )

                    next_element, ambiguous_navigation = self._navigation_element(
                        observation, selected_choice=selected_choice
                    )
                    if ambiguous_navigation:
                        return self._result(
                            RetrievalStatus.AMBIGUOUS,
                            observation=observation,
                            tools=tools,
                            steps=steps,
                            history=history,
                            mappings=mappings,
                            reason="More than one possible report action was found.",
                            choices=self._navigation_choices(observation),
                        )
                    if next_element is not None:
                        if navigations >= self._config.max_navigations:
                            return self._limit_result(
                                observation,
                                tools,
                                steps,
                                history,
                                mappings,
                                "navigation",
                            )
                        action = AgentAction(
                            type=AgentActionType.CLICK,
                            element_id=next_element,
                            reason="Follow the single clear report-workflow action.",
                            confidence=ConfidenceLevel.HIGH,
                        )
                        if self._looped(loop_counts, action, observation, tools):
                            return self._loop_result(
                                observation, tools, steps, history, mappings
                            )
                        observation = tools.click(action, observation)
                        steps += 1
                        navigations += 1
                        self._record(history, steps, action, tools.current_domain)
                        continue

                    if observation.page_type in {
                        PageType.REPORT_LIST_PAGE,
                        PageType.REPORT_VIEWER,
                    }:
                        return self._result(
                            RetrievalStatus.REPORT_NOT_FOUND,
                            observation=observation,
                            tools=tools,
                            steps=steps,
                            history=history,
                            mappings=mappings,
                            reason="No validated PDF report action was available.",
                        )
                    if (
                        authentication_submissions > 0
                        and post_authentication_waits == 0
                        and self._config.max_wait_seconds > 0
                    ):
                        wait_seconds = min(2.0, self._config.max_wait_seconds)
                        action = AgentAction(
                            type=AgentActionType.WAIT,
                            wait_seconds=wait_seconds,
                            reason="Allow the authenticated report page to finish loading.",
                            confidence=ConfidenceLevel.HIGH,
                        )
                        observation = tools.wait(action)
                        steps += 1
                        post_authentication_waits += 1
                        self._record(history, steps, action, tools.current_domain)
                        continue
                    return self._result(
                        RetrievalStatus.AMBIGUOUS,
                        observation=observation,
                        tools=tools,
                        steps=steps,
                        history=history,
                        mappings=mappings,
                        reason="The next report-retrieval step could not be determined safely.",
                    )

                return self._limit_result(
                    observation, tools, steps, history, mappings, "step"
                )
        except PlanningValidationError:
            return self._result(
                RetrievalStatus.FAILED,
                observation=observation,
                tools=None,
                steps=steps,
                history=history,
                mappings=mappings,
                reason="The retrieval plan failed privacy validation.",
            )
        except InteractionSafetyError as exc:
            logger.warning("Retrieval action blocked by safety validation")
            return self._result(
                RetrievalStatus.USER_INPUT_REQUIRED,
                observation=observation,
                tools=None,
                steps=steps,
                history=history,
                mappings=mappings,
                reason=str(exc),
                requested=["Manual confirmation"],
            )
        except BrowserAgentError as exc:
            logger.warning("Retrieval agent stopped: %s", type(exc).__name__)
            return self._result(
                RetrievalStatus.FAILED,
                observation=observation,
                tools=None,
                steps=steps,
                history=history,
                mappings=mappings,
                reason="The controlled browser could not complete report retrieval.",
            )
        except Exception as exc:
            logger.error("Unexpected retrieval failure: %s", type(exc).__name__)
            return self._result(
                RetrievalStatus.FAILED,
                observation=observation,
                tools=None,
                steps=steps,
                history=history,
                mappings=mappings,
                reason="Report retrieval stopped unexpectedly.",
            )

    def _select_search_result(
        self,
        plan: WorkflowPlan,
        search: SearchObservation,
        *,
        selected_choice: str | None = None,
    ):
        if selected_choice:
            selected = next(
                (item for item in search.results if item.url == selected_choice), None
            )
            if selected is not None:
                return SearchSelection(result=selected, ambiguous=False)
        organization_name = plan.organization.name if plan.organization else None
        return self._search_ranker.select(organization_name, search.results)

    def _portal_target(self, planned_target: str) -> str:
        hostname = (urlsplit(planned_target).hostname or "").casefold()
        return self._portal_url_overrides.get(hostname, planned_target)

    @staticmethod
    def _contains_message(
        observation: BrowserObservation, terms: set[str]
    ) -> bool:
        content = " ".join(observation.errors_or_messages).casefold()
        return any(term in content for term in terms)

    @staticmethod
    def _submit_button(
        observation: BrowserObservation,
        mapped_inputs: set[str],
    ) -> ButtonObservation | None:
        priority = {
            ButtonSemanticAction.VIEW_REPORT: 0,
            ButtonSemanticAction.LOGIN: 1,
            ButtonSemanticAction.SUBMIT: 2,
            ButtonSemanticAction.CONTINUE: 3,
        }
        candidates = [
            item
            for item in observation.buttons
            if not item.disabled and item.semantic_action in priority
        ]
        relevant_forms = {
            form.element_id
            for form in observation.forms
            if mapped_inputs & set(form.input_references)
        }
        associated = [
            item for item in candidates if item.form_reference in relevant_forms
        ]
        if associated:
            candidates = associated
        if not candidates:
            return None
        candidates.sort(key=lambda item: priority[item.semantic_action])
        best_priority = priority[candidates[0].semantic_action]
        best = [
            item for item in candidates if priority[item.semantic_action] == best_priority
        ]
        return best[0] if len(best) == 1 else None

    @staticmethod
    def _download_candidate(
        observation: BrowserObservation,
        *,
        selected_choice: str | None = None,
    ) -> tuple[DownloadCandidate | None, bool]:
        recognized_report_page = observation.page_type in {
            PageType.REPORT_LIST_PAGE,
            PageType.REPORT_VIEWER,
        }
        explicit = [
            item
            for item in observation.download_candidates
            if item.likely_file_type == "pdf"
            or (
                recognized_report_page
                and any(
                    term in item.label.casefold()
                    for term in ("download", "save", "report", "result")
                )
            )
            or (
                any(term in item.label.casefold() for term in ("report", "result"))
                and any(term in item.label.casefold() for term in ("download", "save"))
            )
        ]
        download_all = [
            item
            for item in explicit
            if "all" in item.label.casefold()
            and ("report" in item.label.casefold() or "result" in item.label.casefold())
        ]
        if selected_choice:
            selected = next(
                (item for item in explicit if item.element_id == selected_choice), None
            )
            if selected is not None:
                return selected, False
        if len(download_all) == 1:
            return download_all[0], False
        if len(explicit) == 1:
            return explicit[0], False
        return (None, len(explicit) > 1)

    @staticmethod
    def _navigation_element(
        observation: BrowserObservation,
        *,
        selected_choice: str | None = None,
    ) -> tuple[str | None, bool]:
        buttons = [
            item.element_id
            for item in observation.buttons
            if not item.disabled
            and item.semantic_action
            in {ButtonSemanticAction.VIEW_REPORT, ButtonSemanticAction.CONTINUE}
        ]
        links = [
            item.element_id
            for item in observation.links
            if item.likely_purpose
            in {
                LinkPurpose.PATIENT_PORTAL,
                LinkPurpose.REPORTS,
                LinkPurpose.RESULTS,
                LinkPurpose.LOGIN,
            }
        ]
        candidates = list(dict.fromkeys([*buttons, *links]))
        if selected_choice in candidates:
            return selected_choice, False
        if len(candidates) == 1:
            return candidates[0], False
        return None, len(candidates) > 1

    @staticmethod
    def _navigation_choices(
        observation: BrowserObservation,
    ) -> list[RetrievalChoice]:
        choices = [
            RetrievalChoice(
                label=item.text or "Continue report retrieval",
                value=item.element_id,
            )
            for item in observation.buttons
            if not item.disabled
            and item.semantic_action
            in {ButtonSemanticAction.VIEW_REPORT, ButtonSemanticAction.CONTINUE}
        ]
        choices.extend(
            RetrievalChoice(
                label=item.text or item.domain or "Open report service",
                value=item.element_id,
            )
            for item in observation.links
            if item.likely_purpose
            in {
                LinkPurpose.PATIENT_PORTAL,
                LinkPurpose.REPORTS,
                LinkPurpose.RESULTS,
                LinkPurpose.LOGIN,
            }
        )
        return choices

    @staticmethod
    def _merge_mappings(
        current: list[FieldMatch], new: list[FieldMatch]
    ) -> list[FieldMatch]:
        output = list(current)
        keys = {(item.document_field_ref, item.input_element_id) for item in output}
        for item in new:
            key = (item.document_field_ref, item.input_element_id)
            if key not in keys:
                keys.add(key)
                output.append(item)
        return output

    @staticmethod
    def _record(
        history: list[SafeActionRecord],
        step: int,
        action: AgentAction,
        domain: str | None,
        *,
        semantic_type: str | None = None,
        outcome: str = "completed",
    ) -> None:
        logger.info("Step %d: %s", step, action.type.value.upper())
        history.append(
            SafeActionRecord(
                step=step,
                action_type=action.type,
                element_id=action.element_id,
                document_semantic_type=semantic_type,
                target_domain=domain,
                outcome=outcome,
            )
        )

    @staticmethod
    def _looped(
        counts: dict[tuple[str, str | None, str | None, str | None], int],
        action: AgentAction,
        observation: BrowserObservation,
        tools: RetrievalToolset,
    ) -> bool:
        key = (
            action.type.value,
            action.element_id,
            tools.current_domain,
            observation.page_type.value,
        )
        counts[key] = counts.get(key, 0) + 1
        return counts[key] > 1

    def _loop_result(
        self,
        observation: BrowserObservation,
        tools: RetrievalToolset,
        steps: int,
        history: list[SafeActionRecord],
        mappings: list[FieldMatch],
    ) -> RetrievalResult:
        return self._result(
            RetrievalStatus.FAILED,
            observation=observation,
            tools=tools,
            steps=steps,
            history=history,
            mappings=mappings,
            reason="A repeated browser-action loop was detected and stopped.",
        )

    def _limit_result(
        self,
        observation: BrowserObservation | None,
        tools: RetrievalToolset,
        steps: int,
        history: list[SafeActionRecord],
        mappings: list[FieldMatch],
        limit_name: str,
    ) -> RetrievalResult:
        return self._result(
            RetrievalStatus.FAILED,
            observation=observation,
            tools=tools,
            steps=steps,
            history=history,
            mappings=mappings,
            reason=f"The bounded {limit_name} limit was reached.",
        )

    @staticmethod
    def _result(
        status: RetrievalStatus,
        *,
        observation: BrowserObservation | None,
        tools: RetrievalToolset | None,
        steps: int,
        history: list[SafeActionRecord],
        mappings: list[FieldMatch],
        reason: str,
        requested: list[str] | None = None,
        choices: list[RetrievalChoice] | None = None,
    ) -> RetrievalResult:
        needs_input = status in {
            RetrievalStatus.USER_INPUT_REQUIRED,
            RetrievalStatus.AMBIGUOUS,
        }
        return RetrievalResult(
            status=status,
            downloaded_file=None,
            final_page_type=observation.page_type if observation else None,
            current_domain=(
                tools.current_domain
                if tools and tools.current_domain
                else observation.final_domain
                if observation
                else None
            ),
            steps_completed=steps,
            user_input_requirement=RetrievalUserInputRequirement(
                required=needs_input,
                reason=reason if needs_input else None,
                requested_information=requested or [],
                choices=choices or [],
            ),
            warnings=tools.warnings if tools else [],
            failure_reason=reason,
            safe_action_history=history,
            field_mappings=mappings,
        )
