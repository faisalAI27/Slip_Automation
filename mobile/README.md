# Get My Lab Report — Android client

The default app now uploads a slip to FastAPI, retrieves the result, downloads
validated report files into private app storage, and opens/saves those files.
Gemini credentials and Playwright stay on the Python server, never in the APK.

## Low-storage APK build

The GitHub Actions workflow `.github/workflows/android-apk.yml` runs Python tests,
Flutter analysis and Flutter tests, then builds an installable **arm64 debug APK**
on a cloud runner. Android Studio, an emulator, and the Android SDK do not need
to be installed on your Mac for this build. Download the
`slip-automation-arm64-test-apk` artifact from the successful workflow run.

The default build connects to `http://localhost:8000` in background-job mode.
On a phone, localhost means the phone; connect it to the Mac by USB and run
`adb reverse` as described below. This APK is for testing, not a signed store
release. A phone with a 32-bit-only CPU needs a separate build.

For an existing HTTPS backend, manually run the workflow with its
`api_base_url` and matching `execution_mode` (`background` or `synchronous`).
The workflow must be present on the default branch before GitHub offers its
manual Run workflow button. Branch pushes also run the default USB build.

## Test on a phone through USB

1. Keep the Gemini key only in the ignored root `.env`. Use
   `DOCUMENT_AI_PROVIDER=gemini`, a working `DOCUMENT_AI_MODEL`, and
   `BACKEND_EXECUTION_MODE=background`.
2. Start the backend from the repository root:

   ```bash
   .venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
   ```

3. Install only Android **platform-tools** for `adb` if needed (the full Android
   Studio/SDK is unnecessary for installing an already-built APK). Enable USB
   debugging on the phone, connect it, and accept its authorization prompt.
4. Run:

   ```bash
   adb devices
   adb reverse tcp:8000 tcp:8000
   adb install -r /absolute/path/to/app-debug.apk
   ```

5. Open **Get My Lab Report** and select a slip you are authorized to retrieve.
   The Mac must remain running and connected. This build is not an offline
   retrieval engine. Camera, gallery, external report viewer, and real portal
   behavior still require this physical-device test.

Only debug builds permit cleartext traffic to localhost/127.0.0.1. Network
traffic to other hosts must use HTTPS. Android app backup is disabled because
saved reports can contain medical information.

## API contract

- `API_EXECUTION_MODE=background` (default): upload multipart field `slip` to
  `POST /api/v1/jobs`, poll the job, and download job-owned files.
- `API_EXECUTION_MODE=synchronous`: use `POST /api/v1/retrieve`, download result
  files immediately, then delete the ephemeral server result. This matches the
  current Cloud Run configuration. The upload request allows 16 minutes.
- The server address is a compile-time `API_BASE_URL`. No secret belongs in a
  `--dart-define`. An IAM-private Cloud Run deployment additionally needs an
  authentication integration; this client does not mint Cloud Run ID tokens.
- Downloads are bounded by size, checked for supported signatures, and cached
  before the success screen appears. Failed runs clear partial local downloads.
  View opens the cached file; Download saves it in private app documents.
- Background server files expire using the backend TTL. Temporary client cache
  is cleared at the next retrieval. Explicitly saved reports remain in app files
  until app data is cleared or the app is uninstalled.

## Local Flutter checks

Flutter 3.47.1 / Dart 3.13.1 are used by CI.

```bash
flutter pub get --enforce-lockfile
flutter analyze
flutter test
```

A local APK build requires Android SDK/build tools and Java, even when started
from the Flutter extension in VS Code. The extension is not an APK compiler by
itself. Cloud builds avoid those local dependencies.

```bash
flutter build apk --debug --target-platform android-arm64 \
  --dart-define=API_BASE_URL=http://localhost:8000 \
  --dart-define=API_EXECUTION_MODE=background
```

For a release, configure your own signing key, supply a real HTTPS backend URL,
and build with `--release`. The current Android release signing configuration
still uses the generated debug key and must be replaced before distribution.
Release mode rejects loopback HTTP and mock reports.

## Explicit UI demo mode

Mock reports are now opt-in and unavailable in release mode:

```bash
flutter run --dart-define=USE_MOCK_SERVICE=true \
  --dart-define=MOCK_SCENARIO=multiple
```

Demo mode generates test files and never retrieves a patient report. Available
scenarios are `single`, `multiple`, `badImage`, `networkUnavailable`,
`backendUnavailable`, `verificationRequired`, `additionalInformationRequired`,
`reportNotFound`, and `retrievalFailed`.
