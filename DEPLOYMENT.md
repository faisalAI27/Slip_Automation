# FastAPI Docker deployment

This deployment runs only the FastAPI backend. Streamlit is not installed in the
production image and does not need to be running.

For the request-bound, scale-to-zero Google Cloud Run prototype, see
[`CLOUD_RUN.md`](CLOUD_RUN.md). The instructions below describe the existing
persistent-host/background-job deployment.

## Supported topology

**Single persistent instance → supported MVP deployment.** The current
`LocalJobStore` and `LocalJobRunner` deliberately keep job state and execution in
one Python process. Completed files are temporary and disappear on shutdown or
expiry.

**Horizontal multi-instance scaling → requires an external JobStore/queue.** Do
not run multiple Uvicorn workers or independent replicas behind a load balancer:
a poll or download request can otherwise reach a process that does not own the
job. Keep the existing `JobStore` and `JobRunner` abstractions when adding a
durable database, object storage, and external queue.

## Build and run

From the repository root:

```bash
docker build -t slip-api .
```

Create a deployment-only environment file outside source control. At minimum,
set the selected provider, its model, and the Gemini secret:

```env
APP_ENV=production
DEBUG_MODE=false
PORT=8080

DOCUMENT_AI_PROVIDER=gemini
DOCUMENT_AI_MODEL=gemini-3.7-flash
GEMINI_API_KEY=replace_with_secret_manager_value

BROWSER_HEADLESS=true
BACKEND_EXECUTION_MODE=background
BACKEND_MAX_CONCURRENT_JOBS=1
JOB_TTL_MINUTES=30
ALLOW_INSECURE_REPORT_PORTALS=false
```

Preserve any required browser/provider tuning from the existing environment,
including `GEMINI_BASE_URL`, timeouts, bounded-agent limits, and administrator
verified HTTPS URL rewrites. Keep `PORTAL_URL_OVERRIDES_JSON` and
`PORTAL_HTTPS_HOST_REWRITES_JSON` empty unless an administrator has verified the
target HTTPS origins.

The original liveness-only command remains valid:

```bash
docker run --rm \
  -p 8080:8080 \
  --env-file .env \
  -e PORT=8080 \
  slip-api
```

Then verify liveness:

```bash
curl http://localhost:8080/health
```

For report retrieval, run the non-root Chromium sandbox with the version-matched
Playwright seccomp profile included in this repository:

```bash
docker run --rm \
  -p 8080:8080 \
  --security-opt seccomp=seccomp_profile.json \
  --env-file .env \
  -e PORT=8080 \
  slip-api
```

The additional profile is required for Chromium, not for `/health`. It is the
official Playwright Docker profile: Docker's normal syscall policy plus the user
namespace operations `clone`, `setns`, and `unshare`. Use an equivalent policy
on a deployment platform that does not accept Docker's `--security-opt` syntax.
Do not replace it with `--no-sandbox` or a TLS/security bypass.

The image always starts one Uvicorn worker. `PORT` is configurable, but the
published host/container port pair must match it. Allow up to 120 seconds for a
graceful stop on a slow portal, for example by configuring the host or platform's
termination grace period. Tini forwards `SIGTERM`; the application rejects new
uploads, drains the active retrieval, cancels queued work, closes its Chromium
context, and removes job-owned temporary files before exiting.

## Secrets and transport

Supply `GEMINI_API_KEY` only at runtime using the host/platform secret store or an
ignored environment file. It is not a Docker build argument, image environment
value, or source default. Restrict access to the environment file.

Place the API behind a TLS-enabled reverse proxy or a cloud ingress. The future
Android release application must use only an `https://` backend URL. Do not add a
custom certificate-verification bypass. Direct `http://localhost` access is only
for local host testing.

## Chromium details

The image uses Ubuntu Noble rather than Alpine. It pins the official Playwright
Python image, its manifest digest, and `playwright==1.62.0`; this keeps the Python
driver and installed Chromium revision aligned. The application runs as the
image's non-root `pwuser`, explicitly enables Chromium sandboxing, and never adds
`--no-sandbox`. `seccomp_profile.json` is pinned from Playwright 1.62.0 and
permits the browser's user-namespace sandbox under Docker's syscall filtering.
The image also hardens the available SUID sandbox helper. The
`--disable-dev-shm-usage` browser setting avoids requiring a desktop session or
special shared-memory flag.

## Full container smoke test

Use a test slip for which the portal can complete without CAPTCHA, OTP, or fresh
interactive input:

```bash
scripts/container_e2e.sh /absolute/path/to/test-slip.jpg
```

The script builds the image, starts it with production safety overrides, waits for
`/health`, uploads the slip, polls the job through Gemini and headless Chromium,
downloads the returned report, and validates its file signature. It exits nonzero
if the workflow stops for user input, verification, or retrieval failure.

## Initial resource allocation

Start one persistent instance at **2 vCPU and 2 GiB RAM**; use **4 GiB RAM** when
portals are heavy or when memory headroom matters. Keep
`BACKEND_MAX_CONCURRENT_JOBS=1`. Measure peak RSS during representative retrievals
before reducing the limit; Chromium, image decoding, and document analysis create
short-lived peaks. Increase RAM or CPU before increasing concurrency, then move to
an external queue/store before adding replicas.

The local macOS reference run completed the real upload → Gemini → Chromium →
download path in about 27 seconds. Sampled backend RSS peaked near 107 MiB, while
an isolated headless Chromium launch command peaked near 129 MiB. These are
lower-bound development observations, not container limits; the
2 GiB starting allocation leaves room for Linux Chromium subprocesses, decoded
images, portal variability, and transient memory peaks.
