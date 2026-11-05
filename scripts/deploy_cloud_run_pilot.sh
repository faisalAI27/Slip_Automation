#!/usr/bin/env bash
# Deploy only after the independent-phone pilot's authentication is configured.
set -euo pipefail
if [[ $# -lt 3 || $# -gt 4 ]]; then
  echo 'Usage: bash scripts/deploy_cloud_run_pilot.sh PROJECT_ID REGION IMAGE [ENV_FILE]' >&2
  exit 64
fi
PROJECT_ID=$1
REGION=$2
IMAGE=$3
ENV_FILE=${4:-.env.cloud-run.yaml}
python3 - "$ENV_FILE" "$PROJECT_ID" <<'PY'
import json, re, sys
from pathlib import Path
required = {'API_AUTH_MODE', 'FIREBASE_PROJECT_ID', 'PILOT_ALLOWED_UIDS'}
values = {}
for line in Path(sys.argv[1]).read_text().splitlines():
    key, _, value = line.partition(':')
    if key in required:
        if key in values: raise SystemExit('Duplicate pilot configuration key.')
        values[key] = json.loads(value.strip())
if values.get('API_AUTH_MODE') != 'firebase' or values.get('FIREBASE_PROJECT_ID') != sys.argv[2]:
    raise SystemExit('Pilot requires API_AUTH_MODE="firebase" and the matching Firebase project ID.')
uids = values.get('PILOT_ALLOWED_UIDS', '').split(',')
if not uids or any(not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', uid.strip()) or 'REPLACE' in uid for uid in uids):
    raise SystemExit('Configure actual approved Firebase tester UIDs before deployment.')
print('Pilot authentication configuration checked.')
PY
gcloud run deploy slip-api \
  --project "$PROJECT_ID" --region "$REGION" --image "$IMAGE" \
  --service-account "slip-api-runtime@${PROJECT_ID}.iam.gserviceaccount.com" \
  --execution-environment gen2 --port 8080 \
  --cpu 1 --memory 2Gi --concurrency 1 --min 0 --max 1 --timeout 900s \
  --env-vars-file "$ENV_FILE" \
  --set-secrets GEMINI_API_KEY=slip-gemini-api-key:1 \
  --allow-unauthenticated
