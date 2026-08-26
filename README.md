# Get My Lab Report — Phase 5 + reusable API

The Prompt 3 Android mock client lives in [`mobile/`](mobile/README.md). It is
currently UI-only and does not call the live backend.

This Streamlit app accepts a hospital or laboratory slip image, turns it into a validated semantic representation, builds a deterministic retrieval plan, and uses one bounded private browser session to retrieve a validated PDF or image report when the portal supports safe automation. Document understanding can use Gemini for faster cloud inference, Ollama for local inference, or the existing OpenAI provider. Browser interaction remains deterministic.

> **Current status:** Phases 1–4 upload, understand, plan, and observe. Phase 5 continues from `BROWSER_OBSERVATION_READY`, semantically maps document fields to observed website fields, performs at most one authentication submission, and captures only validated PDF or image reports. A single newest-date report is prepared on its own; when several reports share the newest date, each is retained separately and an optional ZIP is also prepared. CAPTCHA, OTP, undated ambiguous choices, missing fields, unsafe domains, and unsupported portal designs cause a controlled stop.

This application is intended only for retrieving reports that the user or patient is authorized to access. It does not bypass portal authorization or verification controls.

## Run the FastAPI backend

For the production Docker image and single-instance deployment boundary, see
[`DEPLOYMENT.md`](DEPLOYMENT.md).

The API calls the same UI-independent application service used by Streamlit; it does
not move or duplicate the document, planning, browser, or download engines. The first
backend uses a thread-safe in-memory job store and a bounded local thread pool. It is a
development/prototype adapter: jobs do not survive a process restart and should be
replaced with durable shared infrastructure before multi-process deployment.

Start it independently of Streamlit:

```bash
source .venv/bin/activate
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

Upload a slip, poll the returned opaque job ID, and download a completed report using
its job-owned opaque file ID:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/jobs \
  -F "slip=@/absolute/path/to/test-slip.jpg"

curl http://127.0.0.1:8000/api/v1/jobs/JOB_ID

curl -L http://127.0.0.1:8000/api/v1/jobs/JOB_ID/files/FILE_ID \
  --output report.pdf
```

The status response never exposes local paths, credentials, extracted document data,
page content, cookies, or stack traces. Multiple newest-date reports remain separate;
when the engine creates a ZIP, the response also includes independent bundle metadata.
The local store removes expired metadata and all owned uploads/reports/bundles during
job-store activity and explicit cleanup calls.

## Run locally on macOS

Python 3.11 or newer is recommended.

Prepare the project:

```bash
cd /Users/faisalimran/Desktop/Slip_Automation
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
playwright install chromium
cp .env.example .env
```

For the local Ollama fallback, install [Ollama](https://ollama.com/download), start it, and download the vision model once. Check the size reported by Ollama before downloading because model artifacts can change:

```bash
open -a Ollama
ollama pull qwen3-vl:4b-instruct
```

When Ollama is selected, keep it running. Then start Streamlit:

```bash
source .venv/bin/activate
streamlit run app.py
```

Streamlit normally opens `http://localhost:8501`. The camera is not initialized on page load; it appears only after the user chooses **Use camera**.

### Open it on a phone

For immediate local testing, connect the Mac and phone to the same trusted Wi-Fi network and open Streamlit's **Network URL**. Select **Upload photo** and choose the phone's Camera/Take Photo option.

The live **Use camera** widget requires HTTPS on mobile browsers. A private development option is to install Tailscale on the Mac and phone, sign in to the same private network, and run:

```bash
tailscale serve --bg 8501
```

Open the private `https://...ts.net` address printed by Tailscale. Do not use a public tunnel for patient documents.

## Configuration

Environment access is centralized in `config/settings.py`.

| Variable | Default | Purpose |
|---|---:|---|
| `APP_ENV` | `development` | Environment label shown in debug mode |
| `DEBUG_MODE` | `false` | Enables the local developer-details section |
| `PORT` | `8000` | FastAPI container listening port |
| `TEMP_DIR` | `temp` | Temporary uploaded-image directory |
| `TEMP_FILE_MAX_AGE_HOURS` | `24` | Age after which stale temporary files are removed |
| `MAX_UPLOAD_MB` | `12` | Per-image upload limit |
| `LOG_LEVEL` | `INFO` | Application log level |
| `DOCUMENT_AI_PROVIDER` | `ollama` | Provider selected by the replaceable provider factory |
| `DOCUMENT_AI_MODEL` | `qwen3-vl:4b-instruct` | Local vision model selected for more reliable small-text and URL reading |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Local Ollama service address |
| `OLLAMA_TIMEOUT_SECONDS` | `420` | Local inference timeout, including first model load |
| `DOCUMENT_AI_API_KEY` | empty | Optional credential for a later paid OpenAI deployment |
| `DOCUMENT_AI_TIMEOUT_SECONDS` | `90` | Optional paid-provider request timeout |
| `GEMINI_API_KEY` | empty | Gemini API credential; set only in the ignored local `.env` |
| `GEMINI_BASE_URL` | `https://generativelanguage.googleapis.com/v1beta/openai/` | Gemini OpenAI-compatible endpoint |
| `GEMINI_TIMEOUT_SECONDS` | `60` | Maximum time for one Gemini document-analysis request |
| `GEMINI_CREDENTIAL_FOCUS_TIMEOUT_SECONDS` | `12` | Maximum time for the optional second credential-validation request |
| `GEMINI_REASONING_EFFORT` | `low` | Low-latency reasoning level for document extraction |
| `BROWSER_HEADLESS` | `true` | Runs isolated Chromium without displaying a browser window |
| `BROWSER_TIMEOUT_SECONDS` | `30` | General browser/inspection timeout |
| `BROWSER_NAVIGATION_TIMEOUT_SECONDS` | `45` | Maximum initial navigation wait |
| `BROWSER_MAX_SEARCH_RESULTS` | `8` | Maximum structured DuckDuckGo results, capped at 10 |
| `AGENT_MAX_STEPS` | `40` | Maximum controlled actions in one retrieval run |
| `AGENT_MAX_NAVIGATIONS` | `24` | Maximum page-changing actions in one retrieval run |
| `AGENT_MAX_FORM_SUBMISSIONS` | `2` | Hard configuration ceiling; authentication is still limited to one attempt |
| `AGENT_MAX_WAIT_SECONDS` | `8` | Maximum configured bounded wait |
| `MAX_REPORT_DOWNLOAD_MB` | `25` | Maximum accepted PDF or image report size |
| `ALLOW_INSECURE_REPORT_PORTALS` | `false` | Explicit local-only opt-in for a verified legacy HTTP report portal |
| `INTERACTION_AI_PROVIDER` | `deterministic` | Reserved optional interaction-reasoning provider; V1 uses deterministic rules |
| `INTERACTION_AI_MODEL` | empty | Reserved optional local interaction model |
| `PORTAL_URL_OVERRIDES_JSON` | `{}` | Optional administrator-managed obsolete-host to verified HTTPS portal mapping |
| `PORTAL_HTTPS_HOST_REWRITES_JSON` | `{}` | Optional HTTP portal hostname to verified HTTPS origin mapping for safe redirects |
| `BACKEND_EXECUTION_MODE` | `background` | `background` for the local job API; `synchronous` for request-bound Cloud Run retrieval |
| `BACKEND_MAX_CONCURRENT_JOBS` | `1` | Maximum simultaneous local API retrievals/Chromium sessions |
| `JOB_TTL_MINUTES` | `30` | Lifetime of local job metadata and owned temporary files |
| `API_ALLOWED_ORIGINS` | empty | Comma-separated browser origins allowed by CORS; wildcard origins are ignored |

Ollama mode does not read or require an API key. If Ollama is stopped, the app asks the developer to start it. If the configured model has not been downloaded, Developer Mode shows the safe configuration reason.

## AI provider

Provider selection is controlled entirely through `.env`; no source-code changes are needed.

### Gemini — recommended for speed

```env
DOCUMENT_AI_PROVIDER=gemini
DOCUMENT_AI_MODEL=gemini-3.7-flash

GEMINI_API_KEY=your_key_here
GEMINI_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
GEMINI_TIMEOUT_SECONDS=60
GEMINI_CREDENTIAL_FOCUS_TIMEOUT_SECONDS=12
GEMINI_REASONING_EFFORT=low
```

Gemini provides faster cloud inference and requires internet access and API credentials. When Gemini is selected, the uploaded slip image is sent to the configured Gemini API for document understanding. The independent QR decoder still runs locally.

Gemini uses the OpenAI-compatible structured Chat Completions interface. If its preferred parsed-output helper is unavailable, the provider makes a controlled JSON-schema request and still validates the response locally. Low reasoning effort keeps routine document extraction responsive. Transient connection, rate-limit, or server-capacity failures receive at most one application-level retry; a full timeout is never retried.

For latency-sensitive document parsing, set `DOCUMENT_AI_MODEL=gemini-3.5-flash-lite`. For more difficult documents where maximum extraction quality matters more than speed, use `DOCUMENT_AI_MODEL=gemini-3.7-flash`. The provider and validation pipeline are unchanged when switching models.

### Ollama — local fallback

```env
DOCUMENT_AI_PROVIDER=ollama
DOCUMENT_AI_MODEL=qwen3-vl:4b-instruct
```

Ollama keeps document understanding on this Mac and requires no cloud API, but it can be slower on limited hardware.

The existing OpenAI provider remains available:

```env
DOCUMENT_AI_PROVIDER=openai
DOCUMENT_AI_MODEL=gpt-5.6-terra
DOCUMENT_AI_API_KEY=your_api_key_here
```

## Test the complete Phase 5 flow

1. Configure Gemini as shown above, or run `open -a Ollama` and confirm `ollama list` contains `qwen3-vl:4b-instruct` for local mode. The smaller `qwen3-vl:2b-instruct` remains an optional faster Ollama fallback, but it is less reliable for small printed URLs.
2. Optionally set `DEBUG_MODE=true` to inspect structured output locally.
3. Start the app and upload a clear JPG or PNG containing the whole slip.
4. Select **Get report**. Provider startup or temporary cloud demand can make an occasional request slower.
5. Phase 2 analyzes the temporary image using the selected provider and Phase 3 immediately creates a plan. QR decoding remains local in every mode.
6. For `READY` or `SEARCH_REQUIRED`, Phase 4 safely observes the public report service.
7. Phase 5 restarts one private browser session, uses high-confidence semantic mappings, submits authentication at most once, and observes again after every page-changing action.
8. A single newest-date report gets its own **View** and **Download** controls. If several reports share the newest date, every report gets separate **View** and **Download** controls and the app also offers an optional ZIP containing all of them. Missing fields, undated ambiguous choices, CAPTCHA, OTP, unsafe HTTP forms, and unknown credential destinations stop safely.
9. In Developer details, compare the safe document provider, model, and analysis duration, then review the sanitized agent status, action history, field mappings, observations, and download validation metadata. API keys, image data, request payloads, field values, and the local report path are omitted.

Useful manual cases:

- A hospital slip with a URL, patient identifier, and access credential.
- A laboratory registration slip with a QR code but no printed URL.
- A slip with a patient/reference number but no URL or access code.
- A blurred or cropped photo; it should request a clearer image and avoid guessing.
- A clearly non-medical image; it should be rejected gracefully.
- A slip whose URL was read incorrectly by the vision model; a non-resolving or private destination must stop with a safe browser error rather than being guessed or opened.

Run the local automated suite with:

```bash
source .venv/bin/activate
python -m unittest discover -s tests -v
```

The automated browser tests use mocks and synthetic semantic snapshots rather than live medical portals. They cover earlier phases plus semantic field matching, HTTP and cross-domain credential blocking, one-time authentication, CAPTCHA/OTP handoff, search ranking, tied newest-date selection, legacy scripted report controls, transient report frames, HTML/image viewers, per-report preview/download controls, embedded resources, prompt-injection text, hallucinated references, loop and step limits, popup/download controls, PDF/image signature and size checks, sensitive logging, Streamlit state transitions, and session cleanup.

## Architecture

```text
.
├── app.py
├── backend/                         # FastAPI routes and local job infrastructure
├── services/                        # UI-independent retrieval service and safe progress models
├── config/
│   └── settings.py                  # Central environment configuration
├── document_understanding/
│   ├── models.py                    # Strict extensible semantic models
│   ├── prompts.py                   # Central whole-document prompt
│   ├── provider.py                  # Provider protocol, errors, and factory
│   ├── ollama_provider.py           # Default free local implementation
│   ├── gemini_provider.py           # Gemini OpenAI-compatible implementation
│   ├── openai_provider.py           # Optional OpenAI implementation
│   ├── parser.py                    # Structured-output parsing
│   ├── validation.py                # URL checks, normalization, deduplication
│   ├── qr.py                        # Independent non-blocking QR decoding
│   └── service.py                   # Pipeline orchestration
├── ui/
│   ├── main_page.py                 # Session and workflow orchestration
│   ├── components.py                # Normal-user presentation
│   ├── developer_view.py            # Structured sensitive debug view
│   └── styles.py                    # Responsive visual layer
├── workflow/
│   ├── models.py                    # Strict workflow-plan and next-action models
│   ├── rules.py                     # Deterministic candidate and priority rules
│   ├── validation.py                # URL, deduplication, privacy, and plan checks
│   ├── planner.py                   # Phase 3 orchestration
│   └── state.py                     # Workflow states through validated download
├── browser_agent/
│   ├── models.py                    # Strict execution and observation models
│   ├── safety.py                    # Scheme, DNS, private-network, redirect safety
│   ├── session.py                   # Ephemeral Playwright Chromium context
│   ├── search.py                    # DuckDuckGo browser-search abstraction
│   ├── selectors.py                 # Static value-free semantic snapshot script
│   ├── inspector.py                 # Compact deterministic page understanding
│   ├── executor.py                  # Single-action Phase 4 orchestration
│   ├── agent.py                     # Bounded observe-decide-validate-act loop
│   ├── interaction.py               # Trusted Phase 5 tool execution and ranking
│   ├── field_matcher.py             # Organization-independent semantic mapping
│   ├── download_manager.py          # Generated filenames and report-file validation
│   ├── tools.py                     # Explicit Phase 4 and Phase 5 allowlists
│   └── errors.py                    # Controlled browser error taxonomy
├── utils/                           # Temporary-file and privacy-safe logging helpers
└── tests/
```

The UI and workflow depend only on `DocumentVisionProvider`, not directly on a vendor SDK, so another remote or local vision provider can be added without changing the rest of the application.

## Data and privacy notes

- Uploaded filenames are not used as storage names; temporary images receive generated names.
- The current run's files are removed when the user starts over, and stale files are cleaned according to configuration.
- Uploaded images, `.env`, and generated artifacts are excluded from Git.
- Logs record workflow state and categorical status only—not extracted names, IDs, access codes, passwords, or complete results.
- Debug mode can reveal sensitive extracted data locally and is clearly labelled; avoid screenshots and keep it disabled outside testing.
- In Ollama mode, AI inference stays on the Mac and no external AI service receives the image.
- In Gemini mode, the uploaded slip image is sent to the configured Gemini API for document understanding. Do not claim or assume that this processing is local.
- Phase 4 necessarily contacts the selected public website or DuckDuckGo. Search queries are validated twice and may contain organization/public terms only.
- Chromium uses a non-persistent private context with service workers blocked and no saved profile. Unsolicited downloads and popups are blocked; expected validated report actions are temporarily allowed.
- Page HTML and screenshots are not stored. Structured page text is bounded, and input values are never captured.
- All webpage content is treated as untrusted observation data. It cannot change the workflow goal, allowed actions, or privacy rules.
- An HTTP Wi-Fi connection is not appropriate for real patient documents. Use private HTTPS or test with synthetic documents.
- If the OpenAI provider is selected, the image is sent to that provider. Its request uses `store=False`.
- Local processing is not by itself a complete medical-data security or compliance program. A real deployment still requires organization-specific retention, access-control, encryption, consent, audit, and legal review.

DuckDuckGo or a medical portal may present human verification to automated Chromium. The app stops safely and does not attempt to bypass CAPTCHA, OTP, email verification, or other access controls.

When automatic discovery stops, the app shows the URL it extracted and offers one optional, prefilled public-website correction field. User-supplied portal URLs and missing report fields are treated as sensitive and validated before a restarted retrieval run. Normal successful scans require no extra input.

If an organization has retired a URL that remains printed on its slips, an administrator can configure a migration without adding hospital-specific application logic:

```env
PORTAL_URL_OVERRIDES_JSON={"old-reports.hospital.example":"https://reports.hospital.example/login"}
PORTAL_HTTPS_HOST_REWRITES_JSON={"legacy-reports.hospital.example":"https://reports.hospital.example"}
```

The destinations still pass the normal public-address, HTTPS, form-action, and element safety checks. The host rewrite preserves the requested path and query, blocks the HTTP request, and continues with a fresh GET on the configured HTTPS origin. It never replays a credential-bearing POST. Configure either mapping only after independently verifying the destination's ownership and TLS certificate.

Generated report files use names such as `lab_report_<random-id>.pdf`; remote filenames, patient names, identifiers, and access codes are never used as local filenames. Invalid, oversized, or unsupported downloads are deleted. Validated PDF, PNG, and JPEG reports are supported. When several reports share the newest date, their individual validated files remain available for preview/download and a generated ZIP contains the same set. The current run's reports, bundle, and image are removed when **Scan another slip** is selected, and stale files are removed at application startup.
