# Project review — November 5, 2026

## GitHub and local state

Repository: [faisalAI27/Slip_Automation](https://github.com/faisalAI27/Slip_Automation).
Local project: `slip_automation/Slip_Automation/` inside the current workspace.

After fetching GitHub, the local checkout was clean and exactly matched
`origin/codex/mobile-api-apk` at `1dc9c87721235aa7b673ed1b8477cdbf8555fdca`.
There were no unmerged files or local changes. Local `main` and GitHub `main`
were at `e99a5890836ac5d267620a30d64d3677f7b24917`.
The mobile branch was four commits ahead of main and zero commits behind:

- `0af743f` — Connect Android client to report backend
- `5e2e7e4` — Fix Android CI SDK setup
- `4430cb6` — Support verified legacy report portal
- `1dc9c87` — Configure NWGH report portal

This baseline predates the hospital-selection and repository-organization commits.
Integration into main is tracked in [pull request #1](https://github.com/faisalAI27/Slip_Automation/pull/1).
Existing APKs beside the source tree are separate build artifacts; their presence
does not verify that they contain the current source. Pushing source does not
deploy the backend or install a new APK on a phone.

## How the project works

1. **Capture and upload:** Streamlit (`ui/`) and Flutter Android (`mobile/`)
   accept a slip photo and the hospital choice. Temporary files use generated names.
2. **Understand the document:** `document_understanding/` calls the selected
   vision provider (Gemini, Ollama, or OpenAI), decodes QR codes independently,
   validates structured data, and preserves visible identifiers and credentials.
3. **Choose a route:** `services/report_retrieval.py` coordinates the flow.
   Northwest and RMI use explicit profiles in `document_understanding/hospitals.py`.
   Other hospital retains the general `workflow/` planner and organization-only search.
4. **Retrieve:** `browser_agent/` opens an ephemeral Playwright browser, inspects
   forms, matches fields semantically, submits authentication at most once, and
   stops on CAPTCHA, OTP, ambiguous choices, or unsafe destinations.
5. **Deliver:** Validated PDF/image files are returned individually, with an
   optional ZIP for multiple reports sharing the newest date. The backend
   exposes opaque result/file identifiers; Android downloads and opens files.

`backend/` provides background jobs for a persistent single process and
request-bound retrieval for Cloud Run. `config/settings.py` centralizes environment
configuration. The same document, planning, browser, and download components are
shared across clients; the new options do not create three separate engines.

## Management and remaining limits

- **Good baseline:** the original 224 Python tests passed before changes.
  The repository has separate application layers, strict models, bounded browser
  actions, safe progress responses, temporary-file cleanup, and an Android CI build.
- **Branch integration:** the Android/backend, hospital-selection, and legacy-portal
  work is tracked on the mobile branch and its pull request. CI runs on pushes to
  that branch, pull requests to main, pushes to main, and manual dispatch.
- **Portal transport:** current hospital HTTP overrides are explicitly for
  development. Production startup rejects `ALLOW_INSECURE_REPORT_PORTALS=true`.
  Northwest's published HTTPS report host failed certificate validation during
  the public-page check; RMI's published report link redirected to its homepage.
  Public legacy forms were inspected without submitting credentials. This review
  did not perform a live patient login or claim end-to-end hospital success.
- **Temporary infrastructure:** jobs and files live in one process/local storage.
  They can disappear on restart or Cloud Run instance replacement. Existing docs
  correctly require external storage and a shared queue/store before scaling.
- **Access boundary:** application routes rely on opaque identifiers, not user
  accounts or per-patient ownership checks. Cloud Run documentation specifies
  authenticated ingress, while the current mobile API client has no identity-token
  integration. A production multi-user service needs those boundaries aligned.
- **Client copy:** the selection screen previously said no photo leaves the phone
  even when a live backend was configured. It now uses wording consistent with
  report retrieval. Cloud vision providers still receive the image when selected.
- **Secrets:** `.env`, temporary slips, and generated reports are ignored. A bounded
  scan of tracked text files found no matching Google API key, GitHub token, or
  private-key patterns; this is not a complete secret-history audit.

## Validation

Automated checks cover all three hospital values in both API execution modes,
invalid selections, focused provider prompts, exact two-field mapping, omitted
selection compatibility, hospital mismatches, uncertain/conflicting credentials,
and the stop-before-browser behavior. Flutter checks cover selection propagation,
reset, multipart uploads, and existing camera/gallery, report, and adaptive-layout
flows, including a 375px phone at maximum text scale with dark mode and reduced
motion. The photo placeholder now grows with its contents rather than clipping
large text. Light and dark hospital-selection screens were rendered and inspected.

The hospital-selection implementation passed **239 Python tests** and **42 Flutter
tests**, with no Flutter analysis issues. Follow-up review fixes add coverage for
request cancellation and enforcement of the synthetic test's Gemini provider flag.
The complete updated suite passes **240 Python tests** and **45 Flutter tests**;
Flutter analysis, documentation link checks, workflow YAML checks, and
`git diff --check` also pass locally. Request deadlines now abort the individual
HTTP request and cancel active response subscriptions, including late responses;
the HTTP client remains usable for retries. `--gemini` rejects other providers.
GitHub Actions records the checks and debug APK build for the pushed commit.
No local APK rebuild or backend deployment was performed.
