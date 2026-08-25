# Get My Lab Report — Android mock client

This Flutter application is the Prompt 3 UI-only client. It selects or captures a
slip image and demonstrates processing, report, and error states with
`MockReportService`. It does not upload the image or contact FastAPI yet.

Python automation, Gemini credentials, browser automation, portal credentials,
and all report-retrieval intelligence remain outside this project.

## Setup

Install a current stable Flutter SDK, then run from this directory:

```bash
flutter pub get
```

Launch on an attached Android device or emulator:

```bash
flutter run \
  --dart-define=API_BASE_URL=https://api.example.com
```

`API_BASE_URL` is read only by `AppConfig`. Non-HTTPS URLs are rejected except
`http://localhost` and `http://127.0.0.1` for local development. Prompt 3 does not
send requests to this URL.

The default mock returns one report. Other UI states can be previewed without a
backend:

```bash
flutter run \
  --dart-define=API_BASE_URL=https://api.example.com \
  --dart-define=MOCK_SCENARIO=multiple
```

Available scenarios are `single`, `multiple`, `badImage`,
`networkUnavailable`, `backendUnavailable`, `verificationRequired`,
`additionalInformationRequired`, `reportNotFound`, and `retrievalFailed`.

## Checks

```bash
flutter analyze
flutter test
```

The Android application ID is `com.slipautomation.reportapp`. The manifest adds
only `android.permission.INTERNET` for the future HTTPS API. Camera capture and
gallery selection use Android system intents/Photo Picker through `image_picker`;
there are no broad storage permissions.
