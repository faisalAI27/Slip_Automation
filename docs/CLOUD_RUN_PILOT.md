# Cloud Run pilot with independent Android access

The phone signs in with Firebase Email/Password authentication, gets a Firebase
ID token, and sends it on every API request. Cloud Run accepts internet requests;
the application verifies the token and permits only explicitly approved tester
UIDs. Every job/result/download is checked against its authenticated owner.
`/health` is public. No Gemini key or service-account credential goes in the APK.

This follows Google's [Cloud Run end-user authentication](https://docs.cloud.google.com/run/docs/authenticating/end-users)
pattern. It differs from the IAM-private development setup in [CLOUD_RUN.md](../CLOUD_RUN.md).

## Configured pilot target

| Setting | Value |
|---|---|
| Firebase / Google Cloud project | `slip-automation-pilot` |
| Cloud Run region | `asia-south1` (Mumbai) |
| Cloud Run service | `slip-api` |
| Android package | `com.slipautomation.reportapp` |
| API mode | `synchronous` |
| API authentication | Firebase Email/Password plus approved tester UIDs |

[`cloud-run.pilot.env.yaml`](../cloud-run.pilot.env.yaml) contains the project-specific
non-secret template. Its tester allowlist is intentionally empty. The ignored local
`.env.cloud-run.yaml` holds the approved tester UID; keep that file out of Git.
Firebase Android client identifiers are supplied through the four Actions variables
described below. The backend URL can only be set after Cloud Run deployment.

## 1. Create the project and testers

1. Open the [Firebase console](https://console.firebase.google.com/) and create a
   project. Note its **project ID**, not just its display name. This creates the
   corresponding Google Cloud project. Enable billing for Cloud Run and Cloud Build.
2. Under Authentication, enable **Email/Password** sign-in. Add a tester account
   in the Users tab and copy its UID. The app has a sign-in form and no sign-up form;
   the backend allowlist is the actual restriction on who can retrieve reports.
3. Register an Android app with package name `com.slipautomation.reportapp`.
   Download its `google-services.json` and keep it locally, outside source control.
   Initialization uses explicit Flutter Firebase options, so no Gradle Google
   Services plugin step is required for this email/password flow.
4. Use the same project for Firebase Authentication and Cloud Run. Start with
   region `asia-south1` if it meets your location requirements; the commands accept
   another region. No region or cloud project has been created by this preparation.

## 2. Prepare Google Cloud Shell

Open [Cloud Shell](https://shell.cloud.google.com/). It already provides `gcloud`,
Git, and Docker, so no local Docker or Google Cloud CLI installation is needed.

```bash
git clone --branch main https://github.com/faisalAI27/Slip_Automation.git
cd Slip_Automation

PROJECT_ID="slip-automation-pilot"
REGION="asia-south1"
TAG="$(git rev-parse --short HEAD)"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/slip-automation/slip-api:${TAG}"
gcloud config set project "$PROJECT_ID"

gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com secretmanager.googleapis.com identitytoolkit.googleapis.com

gcloud artifacts repositories create slip-automation \
  --repository-format=docker --location="$REGION"
gcloud iam service-accounts create slip-api-runtime \
  --display-name="Slip API pilot runtime"
RUNTIME_SA="slip-api-runtime@${PROJECT_ID}.iam.gserviceaccount.com"

gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${RUNTIME_SA}" --role=roles/firebaseauth.viewer
```

The runtime's Authentication Viewer role allows the SDK to check disabled/revoked
tester sessions. See [Firebase authentication permissions](https://docs.cloud.google.com/iam/docs/roles-permissions/firebaseauth).
Resource-create commands are for first setup; on later deployments reuse existing
resources rather than recreating them.

## 3. Store the Gemini secret

Use a Gemini key for the backend's configured document model. Enter it at the
hidden prompt; do not paste it into source files, build arguments, or this chat.

```bash
gcloud secrets create slip-gemini-api-key --replication-policy=automatic
read -r -s -p "Gemini API key: " GEMINI_VALUE
printf '\n'
printf '%s' "$GEMINI_VALUE" | gcloud secrets versions add slip-gemini-api-key --data-file=-
unset GEMINI_VALUE
gcloud secrets add-iam-policy-binding slip-gemini-api-key \
  --member="serviceAccount:${RUNTIME_SA}" --role=roles/secretmanager.secretAccessor
```

The deployment script pins secret version **1** for the first deployment. When
rotating it, create another version and explicitly update the deployment reference.
Cloud Run uses its runtime identity, with no downloaded service-account key.
See [Cloud Run secrets](https://docs.cloud.google.com/run/docs/configuring/services/secrets).

## 4. Build and deploy

```bash
BUILD_SA="$(gcloud builds get-default-service-account --project "$PROJECT_ID")"
BUILD_SA="${BUILD_SA##*/}"
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${BUILD_SA}" --role=roles/cloudbuild.builds.builder

gcloud builds submit --project "$PROJECT_ID" --config cloudbuild.yaml \
  --substitutions="_REGION=${REGION},_TAG=${TAG}" .

cp cloud-run.pilot.env.yaml .env.cloud-run.yaml
```

Set `PILOT_ALLOWED_UIDS` in the ignored `.env.cloud-run.yaml` to the tester UID
from Firebase Authentication. The project and auth mode are already configured.
Use double-quoted values; multiple tester UIDs are separated by commas:

```yaml
API_AUTH_MODE: "firebase"
FIREBASE_PROJECT_ID: "slip-automation-pilot"
PILOT_ALLOWED_UIDS: "REPLACE_WITH_TESTER_UID"
```

Then deploy:

```bash
bash scripts/deploy_cloud_run_pilot.sh "$PROJECT_ID" "$REGION" "$IMAGE"
SERVICE_URL="$(gcloud run services describe slip-api --project "$PROJECT_ID" \
  --region "$REGION" --format='value(status.url)')"
curl --fail "$SERVICE_URL/health"
curl -o /dev/null -s -w '%{http_code}\n' "$SERVICE_URL/api/v1/results/unknown"
```

The second request must return **401**, confirming the public ingress does not
grant unauthenticated API access. The deploy script checks the Firebase project
and tester allowlist before making the service internet-accessible. Keep
`API_AUTH_MODE=firebase` for this setup. Cloud Build explicitly enables BuildKit
for the existing Dockerfile. `.gcloudignore` excludes local secrets and uploads.

## 5. Build the phone app

From the repository root on your Mac, use the downloaded Android Firebase file:

```bash
python3 scripts/firebase_mobile_config.py \
  --config /absolute/path/to/google-services.json \
  --api-url https://YOUR-SERVICE-URL.run.app
cd mobile
flutter pub get --enforce-lockfile
flutter build apk --debug --target-platform android-arm64 \
  --dart-define-from-file=../.env.firebase-defines.json
```

The generated file is ignored and contains the HTTPS API URL, synchronous mode,
Firebase mode, and client app configuration. Firebase client API keys identify
the app/project; they are [not the server authentication secret](https://firebase.google.com/docs/projects/api-keys).
Keep the Gemini key and service-account keys out of it.

For a cloud-built APK, add repository **Actions variables**
`FIREBASE_PROJECT_ID`, `FIREBASE_API_KEY`, `FIREBASE_APP_ID`, and
`FIREBASE_MESSAGING_SENDER_ID` from the generated file. Run the existing workflow
with the service URL, `execution_mode=synchronous`, and `auth_mode=firebase`.
Run the workflow from `main` through the Actions page or the authenticated Mac CLI:

```bash
gh workflow run android-apk.yml --ref main \
  -f api_base_url=https://YOUR-SERVICE-URL.run.app \
  -f execution_mode=synchronous -f auth_mode=firebase
```

Install the new debug APK and sign in with the tester account. No USB connection
to the Mac is required for normal internet use. A store release still needs your
own signing key; the existing release signing configuration is for testing.

## 6. Verify the actual pilot

Use a synthetic slip first. Check sign-in, hospital selection, upload, every
download, sign-out, disabled tester accounts, and a cold start. Verify an account
outside `PILOT_ALLOWED_UIDS` receives 403. Then test an authorized hospital slip;
a healthy process does not prove Gemini, Chromium, or the hospital portal works.

Northwest and RMI's current legacy portals use HTTP. The existing exact-host
allowlist permits those hosts even in production; the broad development flag
remains false. Only the backend-to-hospital hop is HTTP. This is a deliberate
pilot exception and does not make the hospital connection encrypted.

The single-process store is still ephemeral: a restart or instance replacement
can lose results before download. The app downloads immediately, but durable
storage remains necessary for a reliable production rollout. Headless Chromium
with the current sandbox settings must also be verified on the deployed instance.
