#!/usr/bin/env bash
# deploy.sh — one-click deploy of The Agentic Studio.
#
# Stands up the whole stack from a single command:
#   1. provisions GCP infra (setup.sh)
#   2. deploys the movie-mcp backend to Cloud Run
#   3. deploys the movie_director agent to Vertex AI Agent Engine (agent_runtime)
#   4. (optional) registers the agent with a Gemini Enterprise app
#
# Usage:
#   ./deploy.sh <PROJECT_ID> [--region REGION] [--ge APP_ID]
#     <PROJECT_ID>   GCP project to deploy into (required)
#     --region       region for the movie-mcp Cloud Run service + agent (default us-central1)
#     --ge APP_ID    after deploy, register with a Gemini Enterprise app (full resource name:
#                    projects/<num>/locations/<loc>/collections/<c>/engines/<engine_id>)
#     --cleanup      tear down movie-mcp + the setup.sh resources
#
# Runs standalone. No hardcoded project IDs, keys, or credentials — everything comes from args/ADC.
set -euo pipefail
cd "$(dirname "$0")"

PROJECT_ID=""; REGION="us-central1"; GE_APP_ID=""; CLEANUP=0
while [ $# -gt 0 ]; do
  case "$1" in
    --region) REGION="$2"; shift 2;;
    --ge)     GE_APP_ID="$2"; shift 2;;
    --cleanup) CLEANUP=1; shift;;
    -h|--help) grep '^# ' "$0" | sed 's/^# //'; exit 0;;
    -*) echo "unknown flag: $1" >&2; exit 2;;
    *) if [ -z "$PROJECT_ID" ]; then PROJECT_ID="$1"; else echo "unexpected arg: $1" >&2; exit 2; fi; shift;;
  esac
done
[ -n "$PROJECT_ID" ] || { echo "Usage: $0 <PROJECT_ID> [--region REGION] [--ge APP_ID] [--cleanup]" >&2; exit 2; }

gcloud config set project "$PROJECT_ID" >/dev/null

if [ "$CLEANUP" = "1" ]; then
  echo "==> Cleanup: deleting movie-mcp Cloud Run service (region ${REGION}) …"
  gcloud run services delete movie-mcp --project "$PROJECT_ID" --region "$REGION" --quiet 2>/dev/null || true
  ./setup.sh "$PROJECT_ID" "$REGION" --cleanup
  echo "✅ Cleanup done. (Delete the Agent Engine instance from deployment_metadata.json via the console if needed.)"
  exit 0
fi

echo "==> [1/4] Provisioning infrastructure (setup.sh) …"
SETUP_YES=1 ./setup.sh "$PROJECT_ID" "$REGION"

echo "==> [2/4] Deploying movie-mcp backend to Cloud Run (region ${REGION}) …"
gcloud run deploy movie-mcp \
  --source movie \
  --project "$PROJECT_ID" --region "$REGION" \
  --allow-unauthenticated \
  --memory 2Gi --cpu 2 --timeout 900 --max-instances 1 \
  --set-env-vars "GOOGLE_CLOUD_PROJECT=${PROJECT_ID},GOOGLE_CLOUD_LOCATION=global" \
  --quiet
MCP_BASE="$(gcloud run services describe movie-mcp --project "$PROJECT_ID" --region "$REGION" --format='value(status.url)')"
MCP_URL="${MCP_BASE}/mcp"
echo "    movie-mcp URL: ${MCP_URL}"

echo "==> [3/4] Deploying the movie_director agent to Vertex AI Agent Engine …"
agents-cli deploy \
  --project "$PROJECT_ID" --region "$REGION" \
  --update-env-vars "MCP_URL=${MCP_URL},GOOGLE_GENAI_USE_VERTEXAI=TRUE,GOOGLE_CLOUD_LOCATION=global" \
  --no-confirm-project

if [ -n "$GE_APP_ID" ]; then
  echo "==> [4/4] Registering with Gemini Enterprise app ${GE_APP_ID} …"
  agents-cli publish gemini-enterprise \
    --gemini-enterprise-app-id "$GE_APP_ID" \
    --deployment-target agent_runtime --registration-type adk \
    --display-name "The Agentic Studio — movie director" \
    --description "Turns a sentence into a multi-scene short (cast, style, storyboards, video) via the movie-mcp pipeline."
else
  echo "==> [4/4] No --ge APP_ID given; skipping Gemini Enterprise registration."
  echo "    Register later with: agents-cli publish gemini-enterprise --gemini-enterprise-app-id <APP_ID>"
fi

echo "✅ Done. Agent Runtime id recorded in deployment_metadata.json; movie-mcp at ${MCP_URL}"
