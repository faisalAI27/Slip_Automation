# Get My Lab Report — Phase 3

This Streamlit app accepts a hospital or laboratory slip image, turns it into a validated semantic representation, and builds one deterministic next-step plan. Local development uses Ollama, so no API key or API subscription is required. A replaceable provider layer keeps paid deployment options available later.

> **Current status:** Phase 2 performs real document understanding. Phase 3 then selects exactly one safe next action using a fixed priority: printed report URL, relevant QR URL, organization homepage, organization-only web search, or user input/stop. It stops at `PLAN_READY` or `USER_INPUT_REQUIRED`.

Browser automation, website visits, report retrieval, form submission, and downloads are deliberately not implemented yet. A planned `OPEN_URL` or `SEARCH_WEB` action is data for a later phase; Phase 3 does not execute it.

## Run locally on macOS

Python 3.11 or newer is recommended.

Install [Ollama](https://ollama.com/download) once, then prepare the project:

```bash
cd /Users/faisalimran/Desktop/Slip_Automation
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
```

Start Ollama and download the local vision model once. Check the size reported by Ollama before downloading because model artifacts can change:

```bash
open -a Ollama
ollama pull qwen3-vl:2b-instruct
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
| `DOCUMENT_AI_MODEL` | `qwen3-vl:2b-instruct` | Lightweight local vision model for 8 GB development machines |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Local Ollama service address |
| `OLLAMA_TIMEOUT_SECONDS` | `420` | Local inference timeout, including first model load |
| `DOCUMENT_AI_API_KEY` | empty | Optional credential for a later paid OpenAI deployment |
| `DOCUMENT_AI_TIMEOUT_SECONDS` | `90` | Optional paid-provider request timeout |

Ollama mode does not read or require `DOCUMENT_AI_API_KEY`. If Ollama is stopped, the app asks the developer to start it. If the configured model has not been downloaded, Developer Mode shows the safe configuration reason.

For a later paid deployment, switch only the provider configuration:

```env
DOCUMENT_AI_PROVIDER=openai
DOCUMENT_AI_MODEL=gpt-5.6-terra
DOCUMENT_AI_API_KEY=your_api_key_here
```

## Test document understanding and planning

1. Run `open -a Ollama` and confirm `ollama list` contains `qwen3-vl:2b-instruct`.
2. Optionally set `DEBUG_MODE=true` to inspect structured output locally.
3. Start the app and upload a clear JPG or PNG containing the whole slip.
4. Select **Get report**. The first request can be slower while the model loads into memory.
5. Phase 2 analyzes the temporary image locally; Phase 3 immediately creates a plan and stops before any navigation.
6. The normal view shows the extracted document details and a short planning outcome. It never exposes or executes a clickable planned action.
7. In Developer details, review the understanding result and Workflow Plan, including candidates, available fields, exactly one next action, warnings, summary, and optional raw JSON.

Useful manual cases:

- A hospital slip with a URL, patient identifier, and access credential.
- A laboratory registration slip with a QR code but no printed URL.
- A slip with a patient/reference number but no URL or access code.
- A blurred or cropped photo; it should request a clearer image and avoid guessing.
- A clearly non-medical image; it should be rejected gracefully.

Run the local automated suite with:

```bash
source .venv/bin/activate
python -m unittest discover -s tests -v
```

The tests use synthetic structured payloads and generated blank images; they do not send medical data to an external service and do not require an API key. Planner coverage includes explicit URLs, QR URLs, homepages, privacy-safe searches, missing organization data, unsupported documents, duplicate and unsafe URLs, and sensitive-query rejection.

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
│   └── state.py                     # Workflow states through PLAN_READY
├── browser_agent/                   # Reserved for Phase 4
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
- An HTTP Wi-Fi connection is not appropriate for real patient documents. Use private HTTPS or test with synthetic documents.
- If the optional OpenAI provider is selected later, the image is sent to that provider. Its request uses `store=False`.
- Local processing is not by itself a complete medical-data security or compliance program. A real deployment still requires organization-specific retention, access-control, encryption, consent, audit, and legal review.

Phase 3 does not visit extracted URLs, search the web, or execute inferred actions. It only produces a validated `WorkflowPlan` for a later phase.
