"""Compact semantic webpage inspection with deterministic classification."""

from collections.abc import Mapping
from datetime import date, datetime
import re
from typing import Any
from urllib.parse import urlsplit

from document_understanding.models import ConfidenceLevel

from browser_agent.errors import PageInspectionError
from browser_agent.models import (
    AuthenticationSignals,
    BrowserObservation,
    ButtonObservation,
    ButtonSemanticAction,
    DownloadCandidate,
    DownloadCandidateKind,
    FormObservation,
    HtmlInputType,
    InputFieldObservation,
    LinkObservation,
    LinkPurpose,
    PageType,
    VerificationSignals,
)
from browser_agent.safety import redact_url_for_display, registrable_domain
from browser_agent.selectors import PAGE_SNAPSHOT_SCRIPT
from utils.logger import get_logger


logger = get_logger(__name__)
MAX_FORMS = 20
MAX_INPUTS = 60
MAX_BUTTONS = 60
MAX_LINKS = 80
MAX_MESSAGES = 20
MAX_TEXT_SUMMARY_CHARS = 3_000
MAX_ITEM_TEXT_CHARS = 300


def _clean_text(value: object, limit: int = MAX_ITEM_TEXT_CHARS) -> str | None:
    if value is None:
        return None
    clean = re.sub(r"\s+", " ", str(value)).strip()
    return clean[:limit] if clean else None


def _combined_text(*values: object) -> str:
    return " ".join(filter(None, (_clean_text(value) for value in values))).casefold()


def _input_type(value: object) -> HtmlInputType:
    normalized = (_clean_text(value) or "text").casefold()
    try:
        return HtmlInputType(normalized)
    except ValueError:
        return HtmlInputType.OTHER


def _report_date(*values: object) -> date | None:
    combined = " ".join(str(value or "") for value in values)
    found: list[date] = []
    patterns = (
        (r"\b(20\d{2}[-/.](?:0?[1-9]|1[0-2])[-/.](?:0?[1-9]|[12]\d|3[01]))\b", ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d")),
        (r"\b((?:0?[1-9]|[12]\d|3[01])[-/.](?:0?[1-9]|1[0-2])[-/.](?:19|20)\d{2})\b", ("%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y")),
        (
            r"\b((?:0?[1-9]|[12]\d|3[01])\s+[A-Za-z]{3,9},?\s*(?:19|20)\d{2})\b",
            ("%d %b %Y", "%d %B %Y", "%d %b,%Y", "%d %B,%Y", "%d %b, %Y", "%d %B, %Y"),
        ),
        (r"\b((?:0?[1-9]|[12]\d|3[01])[-/.][A-Za-z]{3,9}[-/.](?:19|20)\d{2})\b", ("%d-%b-%Y", "%d-%B-%Y", "%d/%b/%Y", "%d/%B/%Y", "%d.%b.%Y", "%d.%B.%Y")),
        (r"\b([A-Za-z]{3,9}\s+(?:0?[1-9]|[12]\d|3[01]),?\s+(?:19|20)\d{2})\b", ("%b %d, %Y", "%B %d, %Y", "%b %d %Y", "%B %d %Y")),
    )
    for pattern, formats in patterns:
        for match in re.finditer(pattern, combined, flags=re.IGNORECASE):
            value = match.group(1)
            for format_value in formats:
                try:
                    found.append(datetime.strptime(value, format_value).date())
                    break
                except ValueError:
                    continue
    return max(found) if found else None


def _likely_file_type(*values: object) -> str | None:
    combined = _combined_text(*values)
    if "application/pdf" in combined or re.search(r"\.pdf(?:[?#]|$)", combined):
        return "pdf"
    if "image/png" in combined or re.search(r"\.png(?:[?#]|$)", combined):
        return "png"
    if any(term in combined for term in ("image/jpeg", "image/jpg")) or re.search(
        r"\.jpe?g(?:[?#]|$)", combined
    ):
        return "jpeg"
    return None


def _button_action(text: object, html_type: object, context: object = None) -> ButtonSemanticAction:
    combined = _combined_text(text, html_type, context)
    text_only = _combined_text(text)
    if any(term in combined for term in ("slide", "carousel", "slideshow")):
        return ButtonSemanticAction.UNKNOWN
    if any(term in text_only for term in ("download", "pdf", "save", "print")):
        return ButtonSemanticAction.DOWNLOAD
    if any(term in combined for term in ("view report", "view result", "show report")):
        return ButtonSemanticAction.VIEW_REPORT
    if text_only in {"view", "preview", "open"} and any(
        term in combined for term in ("report", "result", "test", "investigation", "laboratory")
    ):
        return ButtonSemanticAction.VIEW_REPORT
    if any(term in combined for term in ("sign in", "log in", "login")):
        return ButtonSemanticAction.LOGIN
    if any(term in combined for term in ("continue", "next", "verify")):
        return ButtonSemanticAction.CONTINUE
    if any(term in combined for term in ("search", "find")):
        return ButtonSemanticAction.SEARCH
    if "submit" in combined:
        return ButtonSemanticAction.SUBMIT
    return ButtonSemanticAction.UNKNOWN


def _link_purpose(text: object, url: object, context: object = None) -> LinkPurpose:
    combined = _combined_text(text, url, context)
    text_only = _combined_text(text)
    if any(term in combined for term in ("download", ".pdf", ".png", ".jpg", ".jpeg", "save report")):
        return LinkPurpose.DOWNLOAD
    if any(term in combined for term in ("patient portal", "patient login")):
        return LinkPurpose.PATIENT_PORTAL
    if any(term in combined for term in ("report", "reports")):
        return LinkPurpose.REPORTS
    if any(term in combined for term in ("result", "results")):
        return LinkPurpose.RESULTS
    if text_only in {"view", "preview", "open"} and any(
        term in combined for term in ("report", "result", "test", "investigation", "laboratory")
    ):
        return LinkPurpose.REPORTS
    if any(term in combined for term in ("login", "log in", "sign in")):
        return LinkPurpose.LOGIN
    if any(term in combined for term in ("support", "help", "contact")):
        return LinkPurpose.SUPPORT
    if any(term in combined for term in ("home", "homepage")):
        return LinkPurpose.HOME
    return LinkPurpose.UNKNOWN


def _visible_summary(value: object) -> str | None:
    raw = str(value or "")
    lines: list[str] = []
    seen: set[str] = set()
    for line in raw.splitlines():
        clean = re.sub(r"\s+", " ", line).strip()
        folded = clean.casefold()
        if not clean or folded in seen:
            continue
        if any(
            clutter in folded
            for clutter in (
                "cookie policy",
                "all rights reserved",
                "privacy policy",
                "terms and conditions",
            )
        ):
            continue
        seen.add(folded)
        lines.append(clean)
        if sum(len(item) + 1 for item in lines) >= MAX_TEXT_SUMMARY_CHARS:
            break
    summary = "\n".join(lines)[:MAX_TEXT_SUMMARY_CHARS]
    return summary or None


def _page_messages(snapshot: Mapping[str, Any], summary: str | None) -> list[str]:
    messages = [
        value
        for item in list(snapshot.get("messages") or [])[:MAX_MESSAGES]
        if (value := _clean_text(item))
    ]
    error_terms = (
        "invalid id",
        "invalid code",
        "invalid credential",
        "authentication failed",
        "incorrect password",
        "report not found",
        "session expired",
        "server error",
        "no reports available",
    )
    for line in (summary or "").splitlines():
        if any(term in line.casefold() for term in error_terms):
            messages.append(line[:MAX_ITEM_TEXT_CHARS])
    return list(dict.fromkeys(messages))[:MAX_MESSAGES]


def _verification_signals(
    snapshot: Mapping[str, Any],
    inputs: list[InputFieldObservation],
    summary: str | None,
) -> VerificationSignals:
    input_text = " ".join(
        _combined_text(
            field.name,
            field.label,
            field.placeholder,
            field.aria_label,
        )
        for field in inputs
    )
    page_text = _combined_text(summary, input_text)
    otp_detected = any(
        term in page_text
        for term in (
            "one-time password",
            "one time password",
            "verification code",
            "sms code",
            "otp",
        )
    )
    # `captchaNodes` is already visibility-filtered by the DOM snapshot. Do not
    # infer a challenge from hidden iframe metadata: some portals keep a
    # reCAPTCHA inside a closed account-recovery modal on the normal login page.
    captcha_detected = bool(snapshot.get("captchaNodes")) or any(
        term in page_text for term in ("captcha", "recaptcha", "hcaptcha")
    )
    email_verification = "email verification" in page_text or (
        "verify" in page_text and "email" in page_text
    )
    return VerificationSignals(
        otp_detected=otp_detected,
        captcha_detected=captcha_detected,
        email_verification_detected=email_verification,
        verification_required=otp_detected or captcha_detected or email_verification,
    )


def _authentication_signals(
    inputs: list[InputFieldObservation], buttons: list[ButtonObservation]
) -> AuthenticationSignals:
    credential_terms = {
        "access",
        "code",
        "credential",
        "id",
        "login",
        "mr",
        "mrn",
        "password",
        "patient",
        "pin",
        "reference",
        "registration",
        "report",
        "sample",
        "username",
    }
    useful_fields = []
    for field in inputs:
        if field.html_type in {HtmlInputType.CHECKBOX, HtmlInputType.RADIO}:
            continue
        tokens = set(
            re.findall(
                r"[a-z0-9]+",
                _combined_text(
                    field.name,
                    field.label,
                    field.placeholder,
                    field.aria_label,
                ),
            )
        )
        if field.html_type == HtmlInputType.PASSWORD or tokens & credential_terms:
            useful_fields.append(field)
    has_login_button = any(
        button.semantic_action
        in {
            ButtonSemanticAction.LOGIN,
            ButtonSemanticAction.SUBMIT,
            ButtonSemanticAction.VIEW_REPORT,
        }
        for button in buttons
    )
    required = len(useful_fields) >= 2 or (
        len(useful_fields) == 1
        and (
            useful_fields[0].html_type == HtmlInputType.PASSWORD or has_login_button
        )
    )
    confidence = (
        ConfidenceLevel.HIGH
        if required and (len(useful_fields) >= 2 or has_login_button)
        else ConfidenceLevel.MEDIUM
        if required
        else ConfidenceLevel.LOW
    )
    return AuthenticationSignals(
        authentication_required=required,
        field_count=len(useful_fields),
        confidence=confidence,
    )


def _page_type(
    *,
    final_url: str,
    title: str | None,
    summary: str | None,
    authentication: AuthenticationSignals,
    verification: VerificationSignals,
    downloads: list[DownloadCandidate],
    buttons: list[ButtonObservation],
    links: list[LinkObservation],
    messages: list[str],
) -> PageType:
    combined = _combined_text(final_url, title, summary)
    hostname = (urlsplit(final_url).hostname or "").casefold()
    if verification.verification_required:
        return PageType.VERIFICATION_PAGE
    if "duckduckgo." in hostname:
        return PageType.SEARCH_RESULTS
    if messages and any(
        term in combined
        for term in ("error", "not found", "unavailable", "expired", "invalid")
    ):
        return PageType.ERROR_PAGE
    if authentication.authentication_required:
        return PageType.REPORT_LOGIN_PAGE
    if any(
        button.semantic_action == ButtonSemanticAction.VIEW_REPORT
        for button in buttons
    ) and any(term in combined for term in ("report", "result", "laboratory")):
        return PageType.REPORT_LIST_PAGE
    if any(
        link.likely_purpose in {LinkPurpose.REPORTS, LinkPurpose.RESULTS}
        for link in links
    ) and any(term in combined for term in ("reports", "results")):
        return PageType.REPORT_LIST_PAGE
    if downloads and any(term in combined for term in ("report", "result", "pdf")):
        return PageType.REPORT_VIEWER
    if any(
        term in combined
        for term in (
            "laboratory report",
            "lab report",
            "test result",
            "reference range",
            "investigation report",
        )
    ):
        return PageType.REPORT_VIEWER
    if any(term in combined for term in ("patient portal", "patient services")):
        return PageType.PATIENT_PORTAL
    if any(term in combined for term in ("hospital", "laboratory", "diagnostic", "clinic")):
        return PageType.ORGANIZATION_HOMEPAGE
    return PageType.UNKNOWN


class PageInspector:
    """Convert an untrusted browser page into a compact validated observation."""

    def inspect(self, page: object) -> BrowserObservation:
        try:
            title = page.title()  # type: ignore[attr-defined]
            final_url = page.url  # type: ignore[attr-defined]
            snapshot = page.evaluate(PAGE_SNAPSHOT_SCRIPT)  # type: ignore[attr-defined]
        except Exception as exc:
            raise PageInspectionError("The webpage could not be inspected safely.") from exc
        if not isinstance(snapshot, Mapping):
            raise PageInspectionError("The webpage produced an invalid semantic snapshot.")
        return self.from_snapshot(snapshot, final_url=final_url, page_title=title)

    def from_snapshot(
        self,
        snapshot: Mapping[str, Any],
        *,
        final_url: str,
        page_title: str | None,
    ) -> BrowserObservation:
        parsed_final = urlsplit(final_url)
        final_hostname = (parsed_final.hostname or "").casefold()
        final_domain = registrable_domain(final_hostname) if final_hostname else None
        warnings: list[str] = []

        input_fields: list[InputFieldObservation] = []
        input_form_refs: dict[str, str] = {}
        for raw in list(snapshot.get("inputs") or [])[:MAX_INPUTS]:
            if not isinstance(raw, Mapping):
                continue
            ref = _clean_text(raw.get("ref"))
            if not ref:
                continue
            field = InputFieldObservation(
                element_id=ref,
                html_type=_input_type(raw.get("type") or raw.get("tag")),
                name=_clean_text(raw.get("name")),
                label=_clean_text(raw.get("label")),
                placeholder=_clean_text(raw.get("placeholder")),
                aria_label=_clean_text(raw.get("ariaLabel")),
                required=bool(raw.get("required")),
                disabled=bool(raw.get("disabled")),
                readonly=bool(raw.get("readOnly")),
                autocomplete=_clean_text(raw.get("autocomplete")),
            )
            input_fields.append(field)
            form_ref = _clean_text(raw.get("formRef"))
            if form_ref:
                input_form_refs[field.element_id] = form_ref

        forms: list[FormObservation] = []
        for raw in list(snapshot.get("forms") or [])[:MAX_FORMS]:
            if not isinstance(raw, Mapping):
                continue
            ref = _clean_text(raw.get("ref"))
            if not ref:
                continue
            action_host = urlsplit(str(raw.get("action") or "")).hostname
            forms.append(
                FormObservation(
                    element_id=ref,
                    name=_clean_text(raw.get("name")),
                    method=_clean_text(raw.get("method")),
                    action_domain=(
                        registrable_domain(action_host.casefold()) if action_host else None
                    ),
                    input_references=[
                        input_ref
                        for input_ref, form_ref in input_form_refs.items()
                        if form_ref == ref
                    ],
                )
            )

        buttons: list[ButtonObservation] = []
        for raw in list(snapshot.get("buttons") or [])[:MAX_BUTTONS]:
            if not isinstance(raw, Mapping):
                continue
            ref = _clean_text(raw.get("ref"))
            if not ref:
                continue
            buttons.append(
                ButtonObservation(
                    element_id=ref,
                    text=_clean_text(raw.get("text")),
                    html_type=_clean_text(raw.get("type")),
                    disabled=bool(raw.get("disabled")),
                    semantic_action=_button_action(
                        raw.get("text"), raw.get("type"), raw.get("context")
                    ),
                    form_reference=_clean_text(raw.get("formRef")),
                    report_date=_report_date(raw.get("context"), raw.get("text")),
                )
            )

        links: list[LinkObservation] = []
        for raw in list(snapshot.get("links") or [])[:MAX_LINKS]:
            if not isinstance(raw, Mapping):
                continue
            ref = _clean_text(raw.get("ref"))
            raw_url = _clean_text(raw.get("url"), limit=2_000)
            text = _clean_text(raw.get("text"))
            if not ref or not raw_url:
                continue
            parsed = urlsplit(raw_url)
            if parsed.scheme.casefold() not in {"http", "https"} or not parsed.hostname:
                continue
            link_domain = registrable_domain(parsed.hostname.casefold())
            purpose = _link_purpose(text, raw_url, raw.get("context"))
            if not text and purpose == LinkPurpose.UNKNOWN:
                continue
            links.append(
                LinkObservation(
                    element_id=ref,
                    text=text,
                    url=redact_url_for_display(raw_url),
                    domain=link_domain,
                    same_domain=bool(final_domain and link_domain == final_domain),
                    likely_purpose=purpose,
                    report_date=_report_date(raw.get("context"), text),
                )
            )

        downloads: list[DownloadCandidate] = []
        for link in links:
            combined = _combined_text(link.text, link.url)
            if link.likely_purpose == LinkPurpose.DOWNLOAD or any(
                term in combined for term in (".pdf", "download", "save report")
            ):
                downloads.append(
                    DownloadCandidate(
                        element_id=link.element_id,
                        label=link.text or "Possible report download",
                    kind=DownloadCandidateKind.LINK,
                    likely_file_type=_likely_file_type(combined),
                    confidence=(
                        ConfidenceLevel.HIGH
                        if _likely_file_type(combined) or "download" in combined
                        else ConfidenceLevel.MEDIUM
                    ),
                    report_date=link.report_date,
                )
            )
        for button in buttons:
            if button.semantic_action == ButtonSemanticAction.DOWNLOAD:
                downloads.append(
                    DownloadCandidate(
                        element_id=button.element_id,
                        label=button.text or "Possible report action",
                        kind=DownloadCandidateKind.BUTTON,
                        likely_file_type=(
                            "pdf"
                            if "pdf" in _combined_text(button.text)
                            else None
                        ),
                        confidence=ConfidenceLevel.MEDIUM,
                        report_date=button.report_date,
                    )
                )

        resources = [
            raw
            for raw in list(snapshot.get("resources") or [])[:MAX_LINKS]
            if isinstance(raw, Mapping)
        ]
        for raw in resources:
            ref = _clean_text(raw.get("ref"))
            raw_url = _clean_text(raw.get("url"), limit=2_000)
            file_type = _likely_file_type(raw_url, raw.get("mime"))
            if not ref or not raw_url or not file_type:
                continue
            parsed = urlsplit(raw_url)
            if parsed.scheme.casefold() not in {"http", "https"} or not parsed.hostname:
                continue
            report_date = _report_date(raw.get("context"))
            label = f"Embedded {file_type.upper()} report"
            if report_date:
                label = f"{label} dated {report_date.isoformat()}"
            downloads.append(
                DownloadCandidate(
                    element_id=ref,
                    label=label,
                    kind=DownloadCandidateKind.EMBEDDED_RESOURCE,
                    likely_file_type=file_type,
                    confidence=ConfidenceLevel.HIGH,
                    report_date=report_date,
                )
            )

        summary = _visible_summary(snapshot.get("visibleText"))
        messages = _page_messages(snapshot, summary)
        verification = _verification_signals(snapshot, input_fields, summary)
        authentication = _authentication_signals(input_fields, buttons)
        page_type = _page_type(
            final_url=final_url,
            title=_clean_text(page_title),
            summary=summary,
            authentication=authentication,
            verification=verification,
            downloads=downloads,
            buttons=buttons,
            links=links,
            messages=messages,
        )
        if verification.captcha_detected:
            warnings.append("A CAPTCHA is present and was not interacted with.")
        if verification.otp_detected:
            warnings.append("An OTP or verification-code step is present and was not used.")

        logger.info("Page inspection completed")
        logger.info("Page classified: %s", page_type.value)
        return BrowserObservation(
            final_url=redact_url_for_display(final_url),
            final_domain=final_domain,
            page_title=_clean_text(page_title),
            page_type=page_type,
            visible_text_summary=summary,
            forms=forms,
            input_fields=input_fields,
            buttons=buttons,
            links=links,
            download_candidates=downloads,
            embedded_resource_count=len(resources),
            authentication_signals=authentication,
            verification_signals=verification,
            errors_or_messages=messages,
            warnings=warnings,
            content_is_untrusted=True,
        )
