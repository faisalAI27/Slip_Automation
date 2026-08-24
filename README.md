# Get My Lab Report — Step 1

This project is the foundation for a document-driven hospital and laboratory report retrieval system. The intended experience is deliberately simple: a person supplies a photo of a slip, starts the process, follows a few reassuring stages, and receives a report file.

> **Current status:** Step 1 currently implements only the interface, file handling, state management, and mock workflow. Document AI and browser automation are not yet implemented.

The current result is a clearly labelled demo text file. No slip is interpreted, no hospital website is contacted, and no real medical report is retrieved.

## Run locally on macOS

Python 3.11 or newer is recommended.

```bash
python3 --version
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
streamlit run app.py
```

Streamlit prints a local address, normally `http://localhost:8501`. Open it in a desktop or mobile browser on the same development machine.

### Open it on a phone

1. Connect the Mac and phone to the same Wi-Fi network.
2. Start the app with `streamlit run app.py`.
3. Open the **Network URL** printed by Streamlit on the phone, such as `http://192.168.1.20:8501`.
4. If macOS asks whether Python may accept incoming connections, choose **Allow**.

The camera is never initialized on page load. It starts only after the user explicitly chooses **Use camera**. For real medical documents, use a trusted private network; the current app is a local interface demo and does not provide production deployment security.

Developer details are available in a collapsed section when `DEBUG_MODE=true`. Set it to `false` for the cleanest normal-user interface.

## Project structure

```text
.
├── app.py                      # Thin application entry point
├── config/
│   └── settings.py             # Central environment configuration
├── ui/
│   ├── main_page.py            # Page/session orchestration
│   ├── components.py           # Reusable UI components
│   └── styles.py               # Small visual system
├── workflow/
│   ├── state.py                # Workflow state model and progress steps
│   └── mock_processor.py       # Demo-only replaceable processor
├── document_understanding/     # Reserved for future document services
├── browser_agent/              # Reserved for future browser automation
├── downloads/
│   └── artifacts.py            # Result-file boundary and demo artifact
├── utils/
│   ├── file_utils.py           # Validation, safe storage, and cleanup
│   └── logger.py               # Central privacy-conscious logging
└── temp/                        # Ignored, short-lived run files
```

## Privacy and temporary files

- Uploaded filenames are never used as storage names.
- Valid uploads receive unique generated filenames in `temp/`.
- The app removes the current run's files when the user starts over and clears stale files after the configured age.
- Uploaded documents and generated reports are excluded from Git.
- Logging records workflow events, not document contents, patient identifiers, credentials, access codes, or extracted medical data.

This is a foundation, not a complete medical-data security program. Before handling real patient data, deployment storage, access control, encryption, retention, audit, consent, and applicable legal requirements must be designed and reviewed.

## Configuration

All environment access is centralized in `config/settings.py`. The sample values in `.env.example` run without credentials. `MOCK_STAGE_DELAY_SECONDS=0` is useful for fast local verification.

## Step 1 boundaries

This version intentionally excludes OCR, QR extraction, AI models, hospital-specific logic, website search, Selenium/Playwright, login or OTP handling, CAPTCHA handling, real report retrieval, and sharing integrations.
