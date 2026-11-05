# Contributing

Start with the [README](README.md) and [architecture](docs/ARCHITECTURE.md).
`main` is the shared integration and deployment branch. For future changes,
create a short-lived feature branch and submit a pull request to `main`.

## Where changes belong

- Hospital fields and prompts: `document_understanding/hospitals.py`.
- Shared retrieval: `services/`, `workflow/`, or `browser_agent/`.
- API contracts: `backend/` and matching `mobile/lib/services/` adapters.
- User interfaces: `ui/` or `mobile/lib/screens/`.
- Setup and design explanations: the relevant linked documentation.

Keep retrieval shared across clients. Preserve optional `hospital=other`
compatibility and update both clients when changing the selection contract.

## Checks

From the repository root, with the Python environment activated:

```bash
python -m unittest discover -s tests -v
git diff --check
```

For mobile changes, run from `mobile/`:

```bash
flutter pub get --enforce-lockfile
flutter analyze --no-pub
flutter test --no-pub
```

Use synthetic fixtures for automated checks. The optional real-Chromium fixture
test is `python -m tests.synthetic_browser_e2e`; `--gemini` additionally requires
`DOCUMENT_AI_PROVIDER=gemini` and sends only its generated image to Gemini.
Live hospital verification requires an authorized slip and a separate manual test.

## Pull requests

Describe the behavior change and checks performed. Note API/deployment changes
and live-portal testing limits. Update docs when setup or behavior changes.
CI runs Python tests, Flutter analysis/tests, and an arm64 debug APK build.
A debug APK is not a signed production release.

Never commit `.env`, API keys, patient slips, downloaded reports, or screenshots
containing patient details. Use generated data and placeholder credentials.
