#!/usr/bin/env bash
# Build the images with Cloud Build and deploy GCP Agentflow to Cloud Run.
#
#   ./deploy/scripts/deploy.sh all             # build, deploy API, deploy UI, wire URLs
#   ./deploy/scripts/deploy.sh backend         # API only
#   ./deploy/scripts/deploy.sh ui              # UI only
#   DRY_RUN=1 ./deploy/scripts/deploy.sh all   # print every command, change nothing
#
# Values come from .env. Production-only overrides are listed below in this script,
# so it is always clear what differs from local development.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

TARGET="${1:-all}"
case "$TARGET" in
    all | backend | ui) ;;
    *) die "usage: deploy.sh [all|backend|ui]" ;;
esac
HELPER="$DEPLOY_DIR/scripts/env_to_cloudrun.py"

require_env GCP_PROJECT_ID GCP_REGION ARTIFACT_REGISTRY_REPO BACKEND_SERVICE_NAME FRONTEND_SERVICE_NAME \
    BACKEND_SERVICE_ACCOUNT FRONTEND_SERVICE_ACCOUNT CLOUD_SQL_CONNECTION_NAME GOOGLE_CLIENT_ID \
    CLOUD_TASKS_QUEUE CLOUD_TASKS_LOCATION
check_gcloud

PROJECT="$(env_get GCP_PROJECT_ID)"
# Every gcloud call in this run targets the project from .env, not the local gcloud default.
export CLOUDSDK_CORE_PROJECT="$PROJECT"
REGION="$(env_get GCP_REGION)"
REPO="$(env_get ARTIFACT_REGISTRY_REPO)"
BACKEND="$(env_get BACKEND_SERVICE_NAME)"
UI="$(env_get FRONTEND_SERVICE_NAME)"
BACKEND_EMAIL="$(env_get BACKEND_SERVICE_ACCOUNT)@${PROJECT}.iam.gserviceaccount.com"
UI_EMAIL="$(env_get FRONTEND_SERVICE_ACCOUNT)@${PROJECT}.iam.gserviceaccount.com"
INVOKER_EMAIL="agentflow-tasks-invoker@${PROJECT}.iam.gserviceaccount.com"
CONNECTION_NAME="$(env_get CLOUD_SQL_CONNECTION_NAME)"
BUCKET="${PROJECT}-agentflow-uploads"
REGISTRY="${REGION}-docker.pkg.dev/${PROJECT}/${REPO}"
TAG="$(date -u +%Y%m%d-%H%M%S)"

# --- Preflight: refuse configurations the backend would reject at startup ------
[[ "$(env_get LLM_PROVIDER)" != "mock" ]] \
    || die "LLM_PROVIDER=mock is not allowed in production. Set gemini or claude in $ENV_FILE"
if [[ "$DRY_RUN" != "1" ]] && ! exists gcloud secrets describe agentflow-database-url; then
    die "secret agentflow-database-url not found. Run ./deploy/scripts/bootstrap_gcp.sh first"
fi

# --- Production overrides (see README: "What changes between local and production") --
BACKEND_OVERRIDES=(
    --override APP_ENV=production
    --override AUTH_MODE=google
    --override LOG_FORMAT=json
    --override GENAI_BACKEND=vertex
    --override STORAGE_BACKEND=gcs
    --override "GCS_BUCKET=$BUCKET"
    --override TASK_BACKEND=cloud_tasks
    --override "CLOUD_TASKS_INVOKER_SA=$INVOKER_EMAIL"
    --override OTEL_ENABLED=true
    --override OTEL_EXPORTER=gcp
)

vpc_flags() {
    local connector
    connector="$(env_get VPC_CONNECTOR)"
    if [[ -n "$connector" ]]; then
        printf '%s\n' "--vpc-connector=$connector" "--vpc-egress=private-ranges-only"
    fi
}

service_url() {
    capture gcloud run services describe "$1" --region="$REGION" --format='value(status.url)'
}

service_exists() {
    exists gcloud run services describe "$1" --region="$REGION"
}

build_images() {
    log "Building images with Cloud Build into $REGISTRY (tag $TAG)"
    run gcloud builds submit "$ROOT_DIR" --config "$DEPLOY_DIR/cloudbuild.yaml" \
        --substitutions="_REGISTRY=$REGISTRY,_TAG=$TAG" --quiet
}

deploy_backend() {
    local ui_origin="$1" public_url="$2"
    local overrides=("${BACKEND_OVERRIDES[@]}" --override "BACKEND_PUBLIC_URL=$public_url")
    if [[ -n "$ui_origin" ]]; then
        overrides+=(--override "CORS_ORIGINS=$ui_origin")
    fi

    local flags=() vpc=()
    mapfile -t flags < <(python3 "$HELPER" --env-file "$ENV_FILE" --service backend "${overrides[@]}")
    mapfile -t vpc < <(vpc_flags)

    log "Deploying API service $BACKEND"
    run gcloud run deploy "$BACKEND" --project="$PROJECT" --region="$REGION" \
        --image="$REGISTRY/api:$TAG" \
        --service-account="$BACKEND_EMAIL" \
        --allow-unauthenticated \
        --port=8080 \
        --cpu="$(env_get BACKEND_CPU)" --memory="$(env_get BACKEND_MEMORY)" \
        --min-instances="$(env_get BACKEND_MIN_INSTANCES)" \
        --max-instances="$(env_get BACKEND_MAX_INSTANCES)" \
        --concurrency=40 --timeout=900 \
        --no-cpu-throttling \
        --add-cloudsql-instances="$CONNECTION_NAME" \
        "${vpc[@]}" \
        "${flags[@]}" \
        --quiet

    # Cloud Tasks calls /internal/... with an OIDC token from this service account.
    run_quiet gcloud run services add-iam-policy-binding "$BACKEND" --region="$REGION" \
        --member="serviceAccount:$INVOKER_EMAIL" --role=roles/run.invoker --quiet
}

deploy_ui() {
    local api_url="$1"
    if [[ -z "$api_url" && "$DRY_RUN" != "1" ]]; then
        die "API service $BACKEND is not deployed yet. Run: ./deploy/scripts/deploy.sh backend"
    fi
    local overrides=(--override "UI_API_BASE_URL=$api_url" --override UI_AUTH_MODE=google)
    local flags=()
    mapfile -t flags < <(python3 "$HELPER" --env-file "$ENV_FILE" --service ui "${overrides[@]}")

    log "Deploying UI service $UI"
    run gcloud run deploy "$UI" --project="$PROJECT" --region="$REGION" \
        --image="$REGISTRY/ui:$TAG" \
        --service-account="$UI_EMAIL" \
        --allow-unauthenticated \
        --port=8080 \
        --cpu=1 --memory=256Mi \
        --min-instances="$(env_get FRONTEND_MIN_INSTANCES)" \
        --max-instances="$(env_get FRONTEND_MAX_INSTANCES)" \
        "${flags[@]}" \
        --quiet
}

BACKEND_URL=""
UI_URL=""
if service_exists "$BACKEND"; then
    BACKEND_URL="$(service_url "$BACKEND")"
fi
if service_exists "$UI"; then
    UI_URL="$(service_url "$UI")"
fi

build_images

if [[ "$TARGET" == "all" || "$TARGET" == "backend" ]]; then
    # Keep the current UI origin in CORS during the redeploy so the UI never breaks.
    deploy_backend "$UI_URL" "${BACKEND_URL:-http://localhost:8080}"
    BACKEND_URL="$(service_url "$BACKEND")"
    run curl -fsS --retry 5 --retry-delay 5 "$BACKEND_URL/readyz"
    echo
fi

if [[ "$TARGET" == "all" || "$TARGET" == "ui" ]]; then
    deploy_ui "$BACKEND_URL"
    UI_URL="$(service_url "$UI")"
fi

# The URLs are only known after the first deploy, so the API is updated with them now.
log "Wiring URLs: API knows its public URL and allows the UI origin"
WIRING="BACKEND_PUBLIC_URL=$BACKEND_URL"
if [[ -n "$UI_URL" ]]; then
    WIRING="$WIRING|CORS_ORIGINS=$UI_URL"
fi
run gcloud run services update "$BACKEND" --region="$REGION" --update-env-vars="^|^$WIRING" --quiet

cat <<SUMMARY
Deployed:
  API: $BACKEND_URL   (docs disabled in production; health: $BACKEND_URL/readyz)
  UI : ${UI_URL:-<not deployed>}

Remaining manual step: add ${UI_URL:-the UI URL} to the OAuth client's
"Authorized JavaScript origins" in Google Auth Platform.
SUMMARY
