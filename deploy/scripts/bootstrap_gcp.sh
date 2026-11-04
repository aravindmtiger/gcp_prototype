#!/usr/bin/env bash
# One-time (and re-runnable) setup of the Google Cloud project for GCP Agentflow.
#
#   ./deploy/scripts/bootstrap_gcp.sh             # apply
#   DRY_RUN=1 ./deploy/scripts/bootstrap_gcp.sh   # print the commands only
#   CREATE_MEMORYSTORE=true ./deploy/scripts/bootstrap_gcp.sh   # also create Redis + VPC connector
#
# Creates: APIs, Artifact Registry repo, service accounts and IAM, Cloud Storage bucket,
# Cloud SQL (PostgreSQL 16 + pgvector), Secret Manager secrets, Cloud Tasks queue.
# Existing resources are kept, so the script can be re-run after a partial failure.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

require_env GCP_PROJECT_ID GCP_REGION ARTIFACT_REGISTRY_REPO BACKEND_SERVICE_ACCOUNT \
    FRONTEND_SERVICE_ACCOUNT CLOUD_SQL_CONNECTION_NAME CLOUD_SQL_TIER CLOUD_SQL_DB CLOUD_SQL_USER \
    CLOUD_TASKS_QUEUE CLOUD_TASKS_LOCATION
check_gcloud

PROJECT="$(env_get GCP_PROJECT_ID)"
REGION="$(env_get GCP_REGION)"
REPO="$(env_get ARTIFACT_REGISTRY_REPO)"
BACKEND_SA="$(env_get BACKEND_SERVICE_ACCOUNT)"
UI_SA="$(env_get FRONTEND_SERVICE_ACCOUNT)"
INVOKER_SA="agentflow-tasks-invoker"
CONNECTION_NAME="$(env_get CLOUD_SQL_CONNECTION_NAME)"
SQL_INSTANCE="${CONNECTION_NAME##*:}"
SQL_DB="$(env_get CLOUD_SQL_DB)"
SQL_USER="$(env_get CLOUD_SQL_USER)"
SQL_TIER="$(env_get CLOUD_SQL_TIER)"
QUEUE="$(env_get CLOUD_TASKS_QUEUE)"
QUEUE_LOCATION="$(env_get CLOUD_TASKS_LOCATION)"
BUCKET="${PROJECT}-agentflow-uploads"
BACKEND_EMAIL="${BACKEND_SA}@${PROJECT}.iam.gserviceaccount.com"
UI_EMAIL="${UI_SA}@${PROJECT}.iam.gserviceaccount.com"
INVOKER_EMAIL="${INVOKER_SA}@${PROJECT}.iam.gserviceaccount.com"

[[ "$CONNECTION_NAME" == "$PROJECT:$REGION:"?* ]] \
    || die "CLOUD_SQL_CONNECTION_NAME must look like $PROJECT:$REGION:<instance-name>"

# Every gcloud call in this run targets the project from .env (no global config change).
export CLOUDSDK_CORE_PROJECT="$PROJECT"

log "Enabling APIs"
run gcloud services enable \
    run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
    secretmanager.googleapis.com sqladmin.googleapis.com aiplatform.googleapis.com \
    cloudtasks.googleapis.com storage.googleapis.com cloudtrace.googleapis.com \
    logging.googleapis.com iam.googleapis.com iamcredentials.googleapis.com \
    vpcaccess.googleapis.com redis.googleapis.com

log "Artifact Registry repository $REPO"
if ! exists gcloud artifacts repositories describe "$REPO" --location="$REGION"; then
    run gcloud artifacts repositories create "$REPO" --repository-format=docker \
        --location="$REGION" --description="GCP Agentflow images"
fi

log "Service accounts"
for sa in "$BACKEND_SA" "$UI_SA" "$INVOKER_SA"; do
    if ! exists gcloud iam service-accounts describe "${sa}@${PROJECT}.iam.gserviceaccount.com"; then
        run gcloud iam service-accounts create "$sa" --display-name="GCP Agentflow: $sa"
    fi
done

log "IAM for the API service account (roles match what the app actually calls)"
for role in roles/aiplatform.user roles/cloudsql.client \
    roles/cloudtrace.agent roles/logging.logWriter roles/cloudtasks.enqueuer; do
    run_quiet gcloud projects add-iam-policy-binding "$PROJECT" --member="serviceAccount:$BACKEND_EMAIL" \
        --role="$role" --condition=None --quiet
done
# Cloud Tasks attaches an OIDC token for the invoker SA, which needs actAs on that SA.
run_quiet gcloud iam service-accounts add-iam-policy-binding "$INVOKER_EMAIL" \
    --member="serviceAccount:$BACKEND_EMAIL" --role=roles/iam.serviceAccountUser --quiet
run_quiet gcloud projects add-iam-policy-binding "$PROJECT" --member="serviceAccount:$UI_EMAIL" \
    --role=roles/logging.logWriter --condition=None --quiet

log "Cloud Storage bucket gs://$BUCKET"
if ! exists gcloud storage buckets describe "gs://$BUCKET"; then
    run gcloud storage buckets create "gs://$BUCKET" --location="$REGION" \
        --uniform-bucket-level-access --public-access-prevention
fi
run_quiet gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" \
    --member="serviceAccount:$BACKEND_EMAIL" --role=roles/storage.objectAdmin --quiet

log "Cloud SQL instance $SQL_INSTANCE (PostgreSQL 16; pgvector is enabled below)"
if ! exists gcloud sql instances describe "$SQL_INSTANCE"; then
    run gcloud sql instances create "$SQL_INSTANCE" --database-version=POSTGRES_16 \
        --tier="$SQL_TIER" --region="$REGION" --edition=ENTERPRISE \
        --backup-start-time=03:00 --storage-auto-increase --deletion-protection
fi
if ! exists gcloud sql databases describe "$SQL_DB" --instance="$SQL_INSTANCE"; then
    run gcloud sql databases create "$SQL_DB" --instance="$SQL_INSTANCE"
fi

if ! exists gcloud secrets describe agentflow-database-url; then
    log "Creating database user $SQL_USER and the agentflow-database-url secret"
    DB_PASSWORD="$(openssl rand -hex 24)"  # hex: safe inside a URL without encoding
    if exists gcloud sql users describe "$SQL_USER" --instance="$SQL_INSTANCE"; then
        action=set-password
    else
        action=create
    fi
    if [[ "$DRY_RUN" == "1" ]]; then
        printf '   [dry-run] gcloud sql users %s %s --instance=%s --password=<generated, hidden>\n' \
            "$action" "$SQL_USER" "$SQL_INSTANCE"
    else
        gcloud sql users "$action" "$SQL_USER" --instance="$SQL_INSTANCE" --password="$DB_PASSWORD" >/dev/null
    fi
    create_secret agentflow-database-url \
        "postgresql+asyncpg://${SQL_USER}:${DB_PASSWORD}@/${SQL_DB}?host=/cloudsql/${CONNECTION_NAME}"
else
    log "Secret agentflow-database-url already exists; keeping the current password"
fi

log "Enabling pgvector and schema grants (gcloud sql import, idempotent)"
INIT_SQL="$(mktemp)"
trap 'rm -f "$INIT_SQL"' EXIT
sed "s/__DB_USER__/${SQL_USER}/" "$DEPLOY_DIR/sql/init.sql.template" > "$INIT_SQL"
run gcloud storage cp "$INIT_SQL" "gs://$BUCKET/bootstrap/init.sql"
SQL_SERVICE_ACCOUNT="$(capture gcloud sql instances describe "$SQL_INSTANCE" --format='value(serviceAccountEmailAddress)')"
run_quiet gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" \
    --member="serviceAccount:$SQL_SERVICE_ACCOUNT" --role=roles/storage.objectViewer --quiet
run gcloud sql import sql "$SQL_INSTANCE" "gs://$BUCKET/bootstrap/init.sql" --database="$SQL_DB" --quiet

log "Cloud Tasks queue $QUEUE ($QUEUE_LOCATION)"
if ! exists gcloud tasks queues describe "$QUEUE" --location="$QUEUE_LOCATION"; then
    run gcloud tasks queues create "$QUEUE" --location="$QUEUE_LOCATION" \
        --max-attempts=5 --min-backoff=5s --max-backoff=300s --max-concurrent-dispatches=10
fi

log "Secret Manager placeholder for the Gemini API key (only needed when GENAI_BACKEND=api_key)"
if ! exists gcloud secrets describe agentflow-gemini-api-key; then
    run gcloud secrets create agentflow-gemini-api-key --replication-policy=automatic
fi

# Least privilege: the API identity can read these two secrets, not every secret in the project.
for secret in agentflow-database-url agentflow-gemini-api-key; do
    run_quiet gcloud secrets add-iam-policy-binding "$secret" --member="serviceAccount:$BACKEND_EMAIL" \
        --role=roles/secretmanager.secretAccessor --quiet
done

if [[ "${CREATE_MEMORYSTORE:-false}" == "true" ]]; then
    log "Memorystore for Redis and Serverless VPC connector (used for rate limiting)"
    if ! exists gcloud redis instances describe agentflow-cache --region="$REGION"; then
        run gcloud redis instances create agentflow-cache --size=1 --region="$REGION" \
            --tier=basic --redis-version=redis_7_2 --connect-mode=DIRECT_PEERING --network=default
    fi
    if ! exists gcloud compute networks vpc-access connectors describe agentflow-connector --region="$REGION"; then
        run gcloud compute networks vpc-access connectors create agentflow-connector --region="$REGION" \
            --network=default --range=10.8.0.0/28
    fi
    REDIS_HOST="$(capture gcloud redis instances describe agentflow-cache --region="$REGION" --format='value(host)')"
    log "Set these in .env: MEMORYSTORE_REDIS_URL=redis://${REDIS_HOST}:6379/0  VPC_CONNECTOR=agentflow-connector"
fi

log "Bootstrap complete."
printf '%s\n' \
    "" \
    "Manual steps that gcloud cannot automate:" \
    "  1. Google Auth Platform: configure the OAuth consent screen (Internal for your Workspace," \
    "     or External with test users), then create an OAuth client ID of type 'Web application'." \
    "     Put its ID in GOOGLE_CLIENT_ID and UI_GOOGLE_CLIENT_ID in .env." \
    "     After the first deploy, add the UI URL to 'Authorized JavaScript origins'." \
    "  2. Optional: GEMINI_API_KEY is only needed for GENAI_BACKEND=api_key. Vertex AI needs no key." \
    "  3. Enable the Claude models you want in Vertex AI Model Garden (console, accept terms)." \
    "" \
    "Next: ./deploy/scripts/deploy.sh all"
