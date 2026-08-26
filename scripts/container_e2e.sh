#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 /absolute/path/to/test-slip.jpg" >&2
  exit 64
fi

SLIP_PATH=$1
IMAGE_NAME=${IMAGE_NAME:-slip-api}
ENV_FILE=${ENV_FILE:-.env}
SECCOMP_PROFILE=${SECCOMP_PROFILE:-seccomp_profile.json}
HOST_PORT=${HOST_PORT:-18000}
CONTAINER_NAME="slip-api-e2e-$$"
BASE_URL="http://127.0.0.1:${HOST_PORT}"
WORK_DIR=$(mktemp -d)

cleanup() {
  docker stop --time 120 "$CONTAINER_NAME" >/dev/null 2>&1 || true
  rm -rf "$WORK_DIR"
}
trap cleanup EXIT INT TERM

command -v docker >/dev/null || {
  echo "Docker is required for this test." >&2
  exit 69
}
[[ -f "$SLIP_PATH" ]] || {
  echo "Test slip not found: $SLIP_PATH" >&2
  exit 66
}
[[ -f "$ENV_FILE" ]] || {
  echo "Environment file not found: $ENV_FILE" >&2
  exit 66
}
[[ -f "$SECCOMP_PROFILE" ]] || {
  echo "Playwright seccomp profile not found: $SECCOMP_PROFILE" >&2
  exit 66
}

docker build -t "$IMAGE_NAME" .
docker image inspect --format '{{json .Config.Env}}' "$IMAGE_NAME" \
  | python3 -c '
import json, sys
values = json.load(sys.stdin)
if any(value.startswith("GEMINI_API_KEY=") for value in values):
    raise SystemExit("image configuration must not contain GEMINI_API_KEY")
'
docker run --detach --rm \
  --name "$CONTAINER_NAME" \
  --stop-timeout 120 \
  -p "${HOST_PORT}:8000" \
  --security-opt "seccomp=$SECCOMP_PROFILE" \
  --env-file "$ENV_FILE" \
  -e APP_ENV=production \
  -e DEBUG_MODE=false \
  -e PORT=8000 \
  -e BROWSER_HEADLESS=true \
  -e BACKEND_EXECUTION_MODE=background \
  -e BACKEND_MAX_CONCURRENT_JOBS=1 \
  -e JOB_TTL_MINUTES=30 \
  -e ALLOW_INSECURE_REPORT_PORTALS=false \
  "$IMAGE_NAME" >/dev/null

for _ in {1..60}; do
  if curl --fail --silent "$BASE_URL/health" >"$WORK_DIR/health.json"; then
    break
  fi
  sleep 1
done

if ! curl --fail --silent "$BASE_URL/health" >/dev/null; then
  docker logs "$CONTAINER_NAME" >&2
  echo "Container did not become healthy." >&2
  exit 1
fi

curl --fail --silent \
  -F "slip=@${SLIP_PATH}" \
  "$BASE_URL/api/v1/jobs" >"$WORK_DIR/created.json"

JOB_ID=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["job_id"])' \
  <"$WORK_DIR/created.json")

STATUS=queued
for _ in {1..180}; do
  curl --fail --silent "$BASE_URL/api/v1/jobs/$JOB_ID" >"$WORK_DIR/status.json"
  STATUS=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["status"])' \
    <"$WORK_DIR/status.json")
  case "$STATUS" in
    completed|failed|user_input_required|verification_required) break ;;
  esac
  sleep 2
done

if [[ "$STATUS" != completed ]]; then
  SAFE_FAILURE=$(python3 -c \
    'import json,sys; data=json.load(sys.stdin); print(data.get("failure_type") or data["status"])' \
    <"$WORK_DIR/status.json")
  echo "End-to-end retrieval did not complete: $SAFE_FAILURE" >&2
  exit 1
fi

FILE_ID=$(python3 -c '
import json, sys
data = json.load(sys.stdin)
reports = data.get("reports") or []
if reports:
    print(reports[0]["file_id"])
elif data.get("bundle"):
    print(data["bundle"]["file_id"])
else:
    raise SystemExit("completed job has no downloadable file")
' <"$WORK_DIR/status.json")

curl --fail --silent --location \
  "$BASE_URL/api/v1/jobs/$JOB_ID/files/$FILE_ID" \
  --output "$WORK_DIR/report"

python3 - "$WORK_DIR/report" <<'PY'
from pathlib import Path
import sys

data = Path(sys.argv[1]).read_bytes()
signatures = (b"%PDF-", b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"PK\x03\x04")
if not data.startswith(signatures):
    raise SystemExit("downloaded report has an unsupported file signature")
print(f"Container E2E passed: downloaded {len(data)} bytes.")
PY

docker stats --no-stream \
  --format 'Container resources at completion: CPU={{.CPUPerc}} memory={{.MemUsage}}' \
  "$CONTAINER_NAME"
