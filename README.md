# Get My Lab Report — Phase 4

This Streamlit app accepts a hospital or laboratory slip image, turns it into a validated semantic representation, builds one deterministic next-step plan, and performs one controlled browser action. Local development uses Ollama and Playwright Chromium, so no API key or API subscription is required.

> **Current status:** Phase 2 understands the document. Phase 3 creates one validated action. For actionable plans only, Phase 4 opens the public URL or performs one organization-only DuckDuckGo search, converts the resulting page into a structured `BrowserObservation`, and stops at `BROWSER_OBSERVATION_READY`.

Phase 4 never fills fields, submits forms, clicks report actions, follows search results, solves CAPTCHA, enters OTP, or downloads reports. Those actions belong to Phase 5.

## Run locally on macOS

Python 3.11 or newer is recommended.

Install [Ollama](https://ollama.com/download) once, then prepare the project:

```bash
cd /Users/faisalimran/Desktop/Slip_Automation
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
playwright install chromium
cp .env.example .env
```

Start Ollama and download the local vision model once. Check the size reported by Ollama before downloading because model artifacts can change:

```bash
open -a Ollama
ollama pull qwen3-vl:4b-instruct
```

Keep Ollama running, then start Streamlit:

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
| `BROWSER_HEADLESS` | `true` | Runs isolated Chromium without displaying a browser window |
| `BROWSER_TIMEOUT_SECONDS` | `30` | General browser/inspection timeout |
| `BROWSER_NAVIGATION_TIMEOUT_SECONDS` | `45` | Maximum initial navigation wait |
| `BROWSER_MAX_SEARCH_RESULTS` | `8` | Maximum structured DuckDuckGo results, capped at 10 |

Ollama mode does not read or require `DOCUMENT_AI_API_KEY`. If Ollama is stopped, the app asks the developer to start it. If the configured model has not been downloaded, Developer Mode shows the safe configuration reason.

For a later paid deployment, switch only the provider configuration:

```env
DOCUMENT_AI_PROVIDER=openai
DOCUMENT_AI_MODEL=gpt-5.6-terra
DOCUMENT_AI_API_KEY=your_api_key_here
```

## Test the complete Phase 4 flow

1. Run `open -a Ollama` and confirm `ollama list` contains `qwen3-vl:4b-instruct`. The smaller `qwen3-vl:2b-instruct` remains an optional faster fallback, but it is less reliable for small printed URLs.
2. Optionally set `DEBUG_MODE=true` to inspect structured output locally.
3. Start the app and upload a clear JPG or PNG containing the whole slip.
4. Select **Get report**. The first request can be slower while the model loads into memory.
5. Phase 2 analyzes the temporary image locally and Phase 3 immediately creates a plan.
6. For `READY` or `SEARCH_REQUIRED`, Phase 4 automatically opens or searches for the public report service, inspects it once, then stops without interacting with forms.
7. The normal view shows **Report service found** when a structured observation is ready.
8. In Developer details, review the understanding result, Workflow Plan, Browser Execution, and Page/Search Observation.

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

The automated browser tests use mocks and synthetic semantic snapshots rather than live medical portals. They cover public URL validation, unsafe schemes, local/private destinations, private DNS resolution, unsafe redirects, search privacy, login-page inspection, OTP/CAPTCHA detection, download candidates, unsupported plans, controlled browser failures, and session cleanup.

## Architecture

```text
.
├── app.py
├── config/
│   └── settings.py                  # Central environment configuration
├── document_understanding/
│   ├── models.py                    # Strict extensible semantic models
│   ├── prompts.py                   # Central whole-document prompt
│   ├── provider.py                  # Provider protocol, errors, and factory
│   ├── ollama_provider.py           # Default free local implementation
│   ├── openai_provider.py           # Optional later paid implementation
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
│   └── state.py                     # Workflow states through browser observation
├── browser_agent/
│   ├── models.py                    # Strict execution and observation models
│   ├── safety.py                    # Scheme, DNS, private-network, redirect safety
│   ├── session.py                   # Ephemeral Playwright Chromium context
│   ├── search.py                    # DuckDuckGo browser-search abstraction
│   ├── selectors.py                 # Static value-free semantic snapshot script
│   ├── inspector.py                 # Compact deterministic page understanding
│   ├── executor.py                  # Single-action Phase 4 orchestration
│   ├── tools.py                     # Phase 4 allowlist and future tool contracts
│   └── errors.py                    # Controlled browser error taxonomy
├── downloads/                       # Reserved for a later retrieval phase
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
- In default Ollama mode, AI inference stays on the Mac and no external AI service receives the image.
- Phase 4 necessarily contacts the selected public website or DuckDuckGo. Search queries are validated twice and may contain organization/public terms only.
- Chromium uses a non-persistent private context with service workers blocked, downloads disabled, no saved profile, and cleanup after the one action.
- Page HTML and screenshots are not stored. Structured page text is bounded, and input values are never captured.
- All webpage content is treated as untrusted observation data. It cannot change the workflow goal, allowed actions, or privacy rules.
- An HTTP Wi-Fi connection is not appropriate for real patient documents. Use private HTTPS or test with synthetic documents.
- If the optional OpenAI provider is selected later, the image is sent to that provider. Its request uses `store=False`.
- Local processing is not by itself a complete medical-data security or compliance program. A real deployment still requires organization-specific retention, access-control, encryption, consent, audit, and legal review.

DuckDuckGo may present a human-verification challenge to automated Chromium. The app stops with a controlled search error and does not attempt to bypass it. Phase 4 ends after one navigation/search and one structured observation; no Phase 5 action is implemented.

When automatic discovery stops, the app shows the URL it extracted and offers one optional, prefilled public-website correction field. A user-supplied URL is validated and inspected without submitting forms. This fallback is shown only after automatic processing fails, so normal successful scans require no extra input.
