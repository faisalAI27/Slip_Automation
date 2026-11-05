# Get My Lab Report

Take a photo of a hospital or laboratory slip and retrieve its available report
as a PDF or image. The project includes an Android app, a Streamlit interface,
and a shared FastAPI report-retrieval backend.

## Hospital options

Choose a hospital before taking or uploading the photo:

| Option | Details read from the slip | Retrieval route |
|---|---|---|
| **Northwest report** | Invoice No. + Access Code | Configured Northwest portal |
| **RMI report** | Username / User ID + Password | Configured RMI portal |
| **Other hospital** | General report-access details, URL, or QR code | Automatic discovery |

Focused modes use only their two required access fields. Missing, uncertain,
conflicting, or wrong-hospital details stop retrieval and request another scan.
Other hospital provides best-effort support for portals the general engine can
understand. The app does not bypass CAPTCHA, OTP, or portal access controls.

## How it works

1. Choose the hospital and capture a clear photo of the complete slip.
2. The vision provider reads and validates the document; QR decoding runs independently.
3. A deterministic planner chooses the configured portal or discovers one.
4. A temporary private browser matches the fields and retrieves available reports.
5. View or save validated PDF/image files. Tied newest-date reports remain separate,
   with an optional ZIP.

## Local setup

Use Python 3.11 or newer. Run these commands from the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
playwright install chromium
cp .env.example .env
```

Configure the vision provider and model in the ignored `.env` file. The default
Ollama provider requires a running local Ollama installation and a downloaded
vision model. Gemini and OpenAI require their respective credentials. See the
[provider guide](docs/TECHNICAL_GUIDE.md#ai-provider).

Start the backend:

```bash
uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Start the web interface in another terminal:

```bash
source .venv/bin/activate
streamlit run app.py
```

For Android setup, USB testing, and cloud-built test APKs, follow the
[mobile guide](mobile/README.md).

## API

Upload a synthetic test slip to the local background-job API:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/jobs \
  -F "slip=@/absolute/path/to/test-slip.jpg" \
  -F "hospital=northwest"
```

Both `POST /api/v1/jobs` and request-bound `POST /api/v1/retrieve` accept
`hospital=northwest|rmi|other`; omitted selections default to `other`, and unknown
values return HTTP 422. Match the route to `BACKEND_EXECUTION_MODE`. Deploy the
updated app and backend together so the hospital choice is honored.

## Repository layout

```text
app.py                    Streamlit entry point
backend/                  FastAPI routes, uploads, jobs, and result responses
services/                 Shared retrieval orchestration and validated files
document_understanding/   Vision providers, QR decoding, hospital profiles
workflow/                 Deterministic planning and workflow state
browser_agent/            Private browser, form matching, safe downloads
config/                   Central environment settings
ui/                       Streamlit screens and presentation
mobile/                   Flutter Android client and tests
tests/                    Python regression and synthetic browser checks
scripts/                  Container smoke-test utilities
docs/                     Architecture, technical guide, and project review
.github/                  CI workflow and pull-request template
```

## Development and documentation

- [Documentation index](docs/README.md)
- [Architecture and data flow](docs/ARCHITECTURE.md)
- [Technical guide and configuration](docs/TECHNICAL_GUIDE.md)
- [Android setup and APK builds](mobile/README.md)
- [Persistent-host deployment](DEPLOYMENT.md)
- [Cloud Run deployment](CLOUD_RUN.md)
- [Independent phone pilot: Firebase sign-in and Cloud Run](docs/CLOUD_RUN_PILOT.md)
- [Project review and known limitations](docs/PROJECT_REVIEW.md)
- [Contributing and checks](CONTRIBUTING.md)

Run `python -m unittest discover -s tests -v` from the root. In `mobile/`, run
`flutter pub get --enforce-lockfile`, `flutter analyze --no-pub`, and
`flutter test --no-pub`. GitHub Actions runs checks and builds an arm64 debug
APK on the development branch, pull requests to `main`, and pushes to `main`.

## Current limitations

The backend uses temporary files and process-local state. It supports one
instance and one worker; durable storage and a shared queue/store are needed
before scaling. The independent-phone pilot uses Firebase sign-in, an approved
tester allowlist, and per-user result ownership; follow the pilot guide above.

The hospitals' published report URLs currently have certificate or redirect
problems. Existing administrator-configured exact-host HTTP exceptions remain
permitted in production; the broad development override is rejected. See the
[dated portal findings](docs/TECHNICAL_GUIDE.md#choose-a-hospital-before-scanning).
Hospital selection does not guarantee successful retrieval from a live portal.

Only process reports the patient/user is authorized to access. Keep `.env`, slips,
reports, and credentials out of Git. Cloud vision modes send the photo to the
selected provider; Ollama inference runs locally. Existing APKs need rebuilding
to include source changes.
