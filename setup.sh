#!/usr/bin/env bash
# setup.sh — provision the GCP resources the Agentic Studio agent + movie-mcp backend need.
#
# Idempotent and safe to re-run. Uses only tools available in Cloud Shell (gcloud, gsutil).
#
# Usage:
#   ./setup.sh <PROJECT_ID> [REGION]            # provision (default REGION=us-central1)
#   ./setup.sh <PROJECT_ID> [REGION] --cleanup  # tear down the resources this script created
#
# Env:
#   SETUP_YES=1   skip the interactive cost-warning confirmation (used by deploy.sh / CI)
set -euo pipefail

PROJECT_ID="${1:-}"
REGION="us-central1"
CLEANUP=0
# optional 2nd positional REGION (unless it's the --cleanup flag)
if [ "${2:-}" != "" ] && [ "${2:-}" != "--cleanup" ]; then REGION="$2"; fi
for arg in "$@"; do [ "$arg" = "--cleanup" ] && CLEANUP=1; done

if [ -z "$PROJECT_ID" ]; then
  echo "Usage: $0 <PROJECT_ID> [REGION] [--cleanup]" >&2
  exit 2
fi

BUCKET="gs://${PROJECT_ID}-movie-studio"
APIS="run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com storage.googleapis.com aiplatform.googleapis.com"

gcloud config set project "$PROJECT_ID" >/dev/null
PROJ_NUM="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
# The default compute service account is the runtime identity for Cloud Run + Agent Engine.
RUNTIME_SA="${PROJ_NUM}-compute@developer.gserviceaccount.com"

if [ "$CLEANUP" = "1" ]; then
  echo "⚠️  CLEANUP: removing resources for ${PROJECT_ID} …"
  gsutil -m rm -r "$BUCKET" 2>/dev/null || echo "  bucket ${BUCKET} already gone"
  gcloud projects remove-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${RUNTIME_SA}" --role="roles/aiplatform.user" --quiet 2>/dev/null || true
  echo "✅ setup cleanup done. (Cloud Run services + Agent Engine: use 'deploy.sh --cleanup' or the console.)"
  exit 0
fi

cat <<EOF
────────────────────────────────────────────────────────────────────
  💸 COST WARNING
  This enables/creates PAID Google Cloud resources on project:
      ${PROJECT_ID}
    • Vertex AI  — image/video/music generation, billed per call
    • Cloud Run  — billed while the movie-mcp service serves traffic
    • Cloud Storage bucket ${BUCKET}
  You are responsible for the charges. Re-run with --cleanup to remove them.
────────────────────────────────────────────────────────────────────
EOF
if [ -z "${SETUP_YES:-}" ] && [ -t 0 ]; then
  read -r -p "Proceed? [y/N] " ans
  case "$ans" in y|Y) ;; *) echo "aborted"; exit 1;; esac
fi

echo "→ enabling APIs …"
gcloud services enable $APIS --project "$PROJECT_ID"

echo "→ ensuring bucket ${BUCKET} …"
gsutil ls -b "$BUCKET" >/dev/null 2>&1 || gsutil mb -l "$REGION" -p "$PROJECT_ID" "$BUCKET"

echo "→ granting IAM to ${RUNTIME_SA} …"
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${RUNTIME_SA}" --role="roles/aiplatform.user" --condition=None >/dev/null
gsutil iam ch "serviceAccount:${RUNTIME_SA}:roles/storage.objectAdmin" "$BUCKET"

echo "✅ setup complete for ${PROJECT_ID} (region ${REGION})."
