# Google Cloud Run pre-deployment guide

This guide prepares the FastAPI container only. It does not start Streamlit and
does not deploy any resource.

## Execution model

`POST /api/v1/jobs` is intentionally a local/persistent-instance API. It returns
`202 Accepted` and then runs `ReportRetrievalService.retrieve()` in an in-process
`ThreadPoolExecutor`. That work is not reliable on a request-billed Cloud Run
service with `min instances = 0`: the request has ended, CPU is no longer
guaranteed, and the process-local job can disappear when the instance scales to
zero.

Set `BACKEND_EXECUTION_MODE=synchronous` on Cloud Run. In this mode:

1. `POST /api/v1/retrieve` accepts multipart field `slip`.
2. The request stays open while the existing `ReportRetrievalService` runs.
3. The response contains safe metadata and a random `result_id`.
4. `GET /api/v1/results/{result_id}` returns the same safe metadata.
5. `GET /api/v1/results/{result_id}/files/{file_id}` streams a validated report.
6. `DELETE /api/v1/results/{result_id}` resets the result and deletes its files.

Creating a background job is rejected while synchronous mode is active. The
existing job routes remain available in `background` mode for local development.
No Gemini or browser logic is duplicated by the synchronous route.

## Prototype state boundary

Results are held in a process-local `LocalJobStore`; slips and reports are held
under `/tmp/slip-automation`. Identifiers and filenames are random. Uploaded
slips are deleted immediately after retrieval. Reports are deleted after the
30-minute result TTL is observed, on process shutdown, or by stale-file cleanup
at the next startup.

Cloud Run's writable filesystem is in memory and disappears with the instance.
It is **not persistent medical storage**. A result can therefore disappear after
the retrieval response but before a later download if the instance is replaced
or scales to zero. `max instances = 1` prevents cross-replica routing, but it
does not make state durable or pin subsequent requests to the same instance.

This is acceptable only for the first synchronous prototype where the client
downloads immediately. Durable production delivery requires an external
`JobStore`, object storage with short-lived authorization, and normally an
external queue. Preserve the existing store abstraction when adding them.

## Container contract

The image is Linux/amd64 compatible when built by Cloud Build. It uses Ubuntu
Noble (not Alpine), one Uvicorn worker, a non-root `pwuser`, and binds
`0.0.0.0:${PORT:-8080}`. Cloud Run injects `PORT`; do not put `PORT` in the
environment file. Streamlit and its dependencies are absent from the backend
image.

The base image and Python package are both Playwright 1.62.0, so Chromium and its
driver match. The official Playwright image supplies Chromium and native Linux
libraries. The application launches headless Chromium with its sandbox enabled;
it does not use `--no-sandbox` and does not weaken the existing private-network,
URL, or TLS checks. Use the second-generation Cloud Run execution environment
for full Linux compatibility.

An Apple Silicon local build is arm64. Use Cloud Build for the deployable
linux/amd64 image, or explicitly use `docker buildx --platform linux/amd64`.

## Production environment

[`cloud-run.env.yaml`](cloud-run.env.yaml) contains the non-secret production
values. Cloud Run supplies `PORT=8080`. The complete runtime configuration is:

| Variable | Production value | Requirement |
|---|---|---|
| `PORT` | injected by Cloud Run (`8080`) | Required platform value |
| `APP_ENV` | `production` | Required |
| `DEBUG_MODE` | `false` | Required and startup-enforced |
| `TEMP_DIR` | `/tmp/slip-automation` | Required |
| `TEMP_FILE_MAX_AGE_HOURS` | `1` | Recommended |
| `MAX_UPLOAD_MB` | `12` | Recommended bound |
| `LOG_LEVEL` | `INFO` | Recommended |
| `DOCUMENT_AI_PROVIDER` | `gemini` | Required |
| `DOCUMENT_AI_MODEL` | `gemini-3.7-flash` | Required; preserve a verified model override |
| `GEMINI_API_KEY` | Secret Manager reference | Required secret; never put in files or image config |
| `GEMINI_BASE_URL` | `https://generativelanguage.googleapis.com/v1beta/openai/` | Required for current provider |
| `GEMINI_TIMEOUT_SECONDS` | `60` | Recommended |
| `GEMINI_CREDENTIAL_FOCUS_TIMEOUT_SECONDS` | `12` | Recommended |
| `GEMINI_REASONING_EFFORT` | `low` | Recommended |
| `BROWSER_HEADLESS` | `true` | Required and startup-enforced |
| `BROWSER_TIMEOUT_SECONDS` | `30` | Recommended |
| `BROWSER_NAVIGATION_TIMEOUT_SECONDS` | `45` | Recommended |
| `BROWSER_MAX_SEARCH_RESULTS` | `8` | Recommended bound |
| `AGENT_MAX_STEPS` | `40` | Recommended bound |
| `AGENT_MAX_NAVIGATIONS` | `24` | Recommended bound |
| `AGENT_MAX_FORM_SUBMISSIONS` | `2` | Recommended bound |
| `AGENT_MAX_WAIT_SECONDS` | `8` | Recommended bound |
| `MAX_REPORT_DOWNLOAD_MB` | `25` | Recommended bound |
| `INTERACTION_AI_PROVIDER` | `deterministic` | Required for current engine |
| `INTERACTION_AI_MODEL` | empty | Optional/reserved |
| `PORTAL_URL_OVERRIDES_JSON` | `{}` | Optional; only administrator-verified HTTPS mappings |
| `PORTAL_HTTPS_HOST_REWRITES_JSON` | `{}` | Optional; only administrator-verified HTTPS rewrites |
| `ALLOW_INSECURE_REPORT_PORTALS` | `false` | Required and startup-enforced |
| `BACKEND_EXECUTION_MODE` | `synchronous` | Required for this Cloud Run prototype |
| `BACKEND_MAX_CONCURRENT_JOBS` | `1` | Kept safe for local job mode |
| `JOB_TTL_MINUTES` | `30` | Recommended ephemeral result lifetime |
| `API_ALLOWED_ORIGINS` | empty | Native Android does not need CORS |

`DOCUMENT_AI_API_KEY`, `DOCUMENT_AI_TIMEOUT_SECONDS`, `OLLAMA_BASE_URL`, and
`OLLAMA_TIMEOUT_SECONDS` are provider-specific and should be omitted in Gemini
mode. Preserve any already verified non-default provider/browser tuning.

## Local image verification

From the repository root:

```bash
docker build -t slip-api .

docker run --rm \
  -p 8080:8080 \
  --env-file .env \
  -e PORT=8080 \
  -e BACKEND_EXECUTION_MODE=synchronous \
  slip-api
```

Then, in another terminal:

```bash
curl http://localhost:8080/health
```

The health route only reports process liveness. It does not initialize Gemini,
launch Chromium, or make an external request.

For a real local Chromium retrieval, add the repository's version-matched Docker
seccomp profile:

```bash
docker run --rm \
  -p 8080:8080 \
  --security-opt seccomp=seccomp_profile.json \
  --env-file .env \
  -e PORT=8080 \
  -e BACKEND_EXECUTION_MODE=synchronous \
  slip-api
```

## Cloud Run resource profile

Use one second-generation instance at a time:

- 1 vCPU
- 2 GiB RAM
- request concurrency 1
- minimum instances 0
- maximum instances 1
- one Uvicorn worker
- request timeout 900 seconds
- request-based CPU allocation

The timeout keeps the synchronous retrieval within one active request. The
mobile/client timeout must be at least as long. If representative retrievals
need more than 15 minutes, do not simply raise the limit: move the operation to
a durable queued design first.

## Build and next deployment command

Create the Artifact Registry repository and Secret Manager secret separately.
Build on Google Cloud so the image is linux/amd64:

```bash
PROJECT_ID="your-project-id"
REGION="your-region"
TAG="prototype-1"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/slip-automation/slip-api:${TAG}"

gcloud builds submit --project "$PROJECT_ID" --tag "$IMAGE" .
```

After the image and secret exist, this is the prepared deployment command. Do
not run it during pre-deployment readiness:

```bash
gcloud run deploy slip-api \
  --project "$PROJECT_ID" \
  --region "$REGION" \
  --image "$IMAGE" \
  --execution-environment gen2 \
  --port 8080 \
  --cpu 1 \
  --memory 2Gi \
  --concurrency 1 \
  --min 0 \
  --max 1 \
  --timeout 900s \
  --env-vars-file cloud-run.env.yaml \
  --set-secrets GEMINI_API_KEY=slip-gemini-api-key:latest \
  --no-allow-unauthenticated
```

Keep the service private until the Android client has an authenticated HTTPS
access design. Cloud Run provides TLS at its service URL; never add an insecure
TLS bypass to the backend or Android client.

## Required post-deployment staging gate

Before real patient use, use a non-sensitive test slip to exercise
upload → synchronous retrieval → Gemini → Playwright → result metadata → every
download. Also test one cold start. This cannot be completed without deploying,
so it remains the explicit gate after this pre-deployment pass.
