# AgentOS

Build, deploy, and manage secure, scalable AI agents using native GCP services.

A GCP-native version of the Agentflow platform. You design a **flow** (an ordered list of
nodes such as *Chat input → Model → Knowledge retriever → Output*), save it, and run it
against a user message. Everything runs on Google Cloud:

- **Cloud Run** hosts the API (FastAPI) and the UI (React, served by nginx).
- **Vertex AI** (Agent Platform) provides Gemini and Claude models and embeddings.
- **Cloud SQL for PostgreSQL + pgvector** stores flows, runs and document chunks.
- **Cloud Storage**, **Memorystore**, **Cloud Tasks**, **Secret Manager**, **Cloud Trace**,
  **Cloud Logging**, **Artifact Registry** and **Cloud Build** cover the rest.

The same code runs locally, in containers, and in production. Its behaviour comes from **one
file**, [`.env`](#2-configuration-the-env-file), so the same code goes from your laptop to Cloud Run
without a code change.

> **Written for:** engineers who are new to this repository and need to run it locally, understand
> how the pieces fit, and deploy it to Google Cloud.

---

## Contents

1. [What is in this repository](#1-what-is-in-this-repository)
2. [Configuration: the `.env` file](#2-configuration-the-env-file)
3. [Architecture](#3-architecture)
4. [Core concepts](#4-core-concepts)
5. [Run it locally](#5-run-it-locally)
6. [API reference](#6-api-reference)
7. [Deploy to Google Cloud](#7-deploy-to-google-cloud)
8. [Production checklist and operations](#8-production-checklist-and-operations)
9. [Extending the code](#9-extending-the-code)
10. [Scope: what is ported, what is not](#10-scope-what-is-ported-what-is-not)
11. [Troubleshooting](#11-troubleshooting)

---

## 1. What is in this repository

```
gcp_claude/
├── .env.example            # the configuration template (copy to .env)
├── docker-compose.yml      # local PostgreSQL+pgvector and Redis (optionally API and UI too)
├── Makefile                # developer commands: `make help`
├── README.md               # this file
│
├── backend/                # FastAPI API (Python 3.12) → Cloud Run
│   ├── pyproject.toml
│   ├── Dockerfile
│   ├── app/
│   │   ├── main.py             # app factory, lifespan, middleware, router wiring
│   │   ├── config.py           # Settings: reads .env, validates production rules
│   │   ├── db.py               # async engine, sessions, schema init (pgvector)
│   │   ├── models.py           # ORM: Flow, Run, DocumentChunk
│   │   ├── schemas.py          # Pydantic models + flow validation rules
│   │   ├── auth.py            # Google ID-token verification, dev auth, Cloud Tasks invoker check
│   │   ├── deps.py             # shared FastAPI dependencies (DB session, user, Redis)
│   │   ├── errors.py           # log_error / sanitize_error_for_user, exception handlers
│   │   ├── logging_setup.py    # text or JSON logs (Cloud Logging severity)
│   │   ├── observability.py    # OpenTelemetry → Cloud Trace (or console)
│   │   ├── routers/            # HTTP endpoints: flows, runs, documents, health
│   │   └── services/
│   │       ├── executor.py     # runs a flow node by node, records step traces
│   │       ├── llm.py          # Gemini (google-genai), Claude (Vertex), mock
│   │       ├── knowledge.py    # chunking, embeddings, pgvector search
│   │       ├── storage.py      # Cloud Storage (or local disk)
│   │       ├── dispatcher.py   # inline background task or Cloud Tasks
│   │       ├── cache.py        # Memorystore (Redis) rate limiter
│   │       └── guardrails.py   # PII redaction before model calls
│   └── tests/              # unit, API (SQLite) and Postgres integration tests
│
├── frontend/               # React + TypeScript + Vite UI → Cloud Run (nginx)
│   ├── package.json, vite.config.ts, tsconfig.json, index.html
│   ├── Dockerfile         # multi-stage: Node build → nginx
│   ├── docker/            # nginx template + runtime config writer
│   ├── public/config.js   # placeholder replaced at container start
│   └── src/
│       ├── main.tsx, App.tsx, config.ts, api.ts, auth.ts, types.ts
│       ├── pages/          # Login, Flows, FlowEditor, Run
│       ├── components/     # Layout, NodeEditor
│       └── lib/nodeTypes.ts  # node catalogue + client-side flow validation (+ tests)
│
└── deploy/                 # everything needed to run in Google Cloud
    ├── cloudbuild.yaml     # builds both images into Artifact Registry
    ├── sql/init.sql.template  # pgvector + schema grants, applied via gcloud sql import
    └── scripts/
        ├── common.sh            # shared helpers (DRY_RUN, env_get, secrets)
        ├── bootstrap_gcp.sh     # one-time project setup (idempotent)
        ├── deploy.sh            # build, deploy API and UI, wire their URLs
        └── env_to_cloudrun.py   # translates .env into Cloud Run flags safely
```

---

## 2. Configuration: the `.env` file

### How it works

1. `cp .env.example .env` once. `.env` is git-ignored, so keep secrets out of `.env.example`.
2. **Backend** (`backend/app/config.py`) loads the root `.env` no matter which directory you start
   from. Real environment variables always win over the file.
3. **Frontend** (`frontend/vite.config.ts`) reads the same file. Only keys starting with `UI_` reach
   the browser bundle, so `DATABASE_URL` never leaks to the client.
4. **Docker / Cloud Run** uses the same keys. `deploy/scripts/env_to_cloudrun.py` converts them
   into Cloud Run flags, sends secrets through Secret Manager, and skips local-only values.
5. **Validation at startup.** The backend refuses to start with an inconsistent configuration.
   For example, `APP_ENV=production` requires `AUTH_MODE=google` and a real model provider, and
   `LLM_PROVIDER=gemini` with an API-key backend requires `GEMINI_API_KEY`.

### Key reference

| Group | Key | Local default | Meaning |
|---|---|---|---|
| Runtime | `APP_ENV` | `local` | `local`, `staging` or `production`. Production enforces strict rules and hides `/docs`. |
| | `LOG_LEVEL`, `LOG_FORMAT` | `INFO`, `text` | `json` for Cloud Logging. |
| | `CORS_ORIGINS` | `http://localhost:5173` | Comma-separated browser origins allowed to call the API. |
| Auth | `AUTH_MODE` | `dev` | `dev` trusts an `X-Dev-User` header (refused in production). `google` verifies Google ID tokens. |
| | `GOOGLE_CLIENT_ID` | empty | OAuth Web client ID. Required when `AUTH_MODE=google`. |
| | `ALLOWED_EMAIL_DOMAINS` | empty | e.g. `example.com`. Empty allows any verified Google account. |
| | `ADMIN_EMAILS` | empty | Can see and run every flow. |
| | `DEV_USER_EMAIL` | `dev@example.com` | Identity used in `dev` mode. |
| Database | `DATABASE_URL` | `postgresql+asyncpg://agentflow:agentflow@localhost:5432/agentflow` | Local Postgres, or the Cloud SQL socket form (set from Secret Manager in production). |
| | `DB_AUTO_CREATE` | `true` | Creates the pgvector extension and tables at startup. |
| | `DB_POOL_SIZE` | `5` | Connection pool size per instance. |
| Cache | `REDIS_URL` | `redis://localhost:6379/0` | Rate limiting. Empty disables it. |
| | `RATE_LIMIT_RUNS_PER_MINUTE` | `30` | Per user. |
| Models | `LLM_PROVIDER` | `mock` | `mock` (offline stub), `gemini`, or `claude` (Claude on Vertex AI). |
| | `GENAI_BACKEND` | `api_key` | `api_key` (Gemini Developer API) or `vertex` (Vertex AI with ADC or the Cloud Run service account). |
| | `GEMINI_API_KEY` | empty | Only for `GENAI_BACKEND=api_key`. Secret in production. |
| | `GCP_PROJECT_ID`, `GCP_LOCATION` | empty, `us-central1` | Required for Vertex AI and Claude. |
| | `GEMINI_MODEL` | `gemini-2.5-flash` | Generation model. |
| | `CLAUDE_MODEL` | `claude-sonnet-5-5` | Must be a model enabled in your project's Vertex AI Model Garden. |
| | `EMBEDDING_MODEL`, `EMBEDDING_DIM` | `text-embedding-005`, `768` | Must match the `document_chunks.embedding` column size. |
| | `LLM_MAX_OUTPUT_TOKENS` | `1024` | Output cap per model call. |
| Storage | `STORAGE_BACKEND` | `local` | `local` (disk) or `gcs` (Cloud Storage). |
| | `LOCAL_STORAGE_DIR`, `GCS_BUCKET` | `./data/storage`, empty | Target for each backend. |
| Dispatch | `TASK_BACKEND` | `inline` | `inline` runs in-process. `cloud_tasks` enqueues on Cloud Tasks. |
| | `CLOUD_TASKS_QUEUE`, `CLOUD_TASKS_LOCATION` | `agentflow-runs`, `us-central1` | Queue used when `cloud_tasks`. |
| | `CLOUD_TASKS_INVOKER_SA` | empty | Service account that Cloud Tasks uses to call the API. |
| | `BACKEND_PUBLIC_URL` | `http://localhost:8080` | Public API URL. It is the OIDC audience for Cloud Tasks. |
| Guardrails | `PII_REDACTION_ENABLED` | `true` | Redacts emails, phone numbers, card numbers and SSNs before model calls. |
| Observability | `OTEL_ENABLED`, `OTEL_EXPORTER` | `false`, `console` | `gcp` exports spans to Cloud Trace. |
| Frontend | `UI_API_BASE_URL` | `http://localhost:8080` | Backend URL the browser calls. |
| | `UI_AUTH_MODE`, `UI_GOOGLE_CLIENT_ID`, `UI_DEV_USER` | `dev`, empty, `dev@example.com` | Mirror the backend auth settings. |
| Deployment | `GCP_PROJECT_ID`, `GCP_REGION`, `ARTIFACT_REGISTRY_REPO` | | Used by the scripts in `deploy/`. Deployment-only keys are never sent to Cloud Run. |
| | `BACKEND_SERVICE_NAME`, `FRONTEND_SERVICE_NAME`, `*_SERVICE_ACCOUNT` | `agentflow-api`, `agentflow-ui`, `agentflow-api-sa`, `agentflow-ui-sa` | Names of the Cloud Run services and identities. |
| | `CLOUD_SQL_CONNECTION_NAME` | empty | `PROJECT:REGION:INSTANCE` for the database. |
| | `MEMORYSTORE_REDIS_URL`, `VPC_CONNECTOR` | empty | Production Redis address and the VPC connector that reaches it. |
| | `*_MIN_INSTANCES`, `*_MAX_INSTANCES`, `BACKEND_CPU`, `BACKEND_MEMORY` | see file | Cloud Run scaling and size. |

### What changes between local and production

The deploy script applies these overrides on top of `.env`. Nothing else is different, so you
can see the full set of changes here:

| Setting | Local (`.env`) | Production (set by `deploy.sh`) |
|---|---|---|
| `APP_ENV` | `local` | `production` |
| `AUTH_MODE` | `dev` | `google` |
| `LOG_FORMAT` | `text` | `json` |
| `GENAI_BACKEND` | `api_key` | `vertex` (no API key, uses the service account) |
| `STORAGE_BACKEND` | `local` | `gcs`, bucket `<project>-agentflow-uploads` |
| `TASK_BACKEND` | `inline` | `cloud_tasks` |
| `OTEL_ENABLED`, `OTEL_EXPORTER` | `false`, `console` | `true`, `gcp` |
| `DATABASE_URL` | localhost | Secret Manager `agentflow-database-url` |
| `REDIS_URL` | localhost | `MEMORYSTORE_REDIS_URL` (or disabled if empty) |
| `CORS_ORIGINS`, `BACKEND_PUBLIC_URL`, `UI_API_BASE_URL` | localhost | The Cloud Run URLs, wired after the first deploy |

Keys that must **never** be sent to Cloud Run as plain text are listed in `SECRET_KEYS` in
`deploy/scripts/env_to_cloudrun.py`. Keys that are only used by the deploy scripts are listed in
`DEPLOY_ONLY_KEYS` in the same file.

### Using a real model locally

The default `LLM_PROVIDER=mock` needs no cloud account. To call real models from your laptop:

```bash
gcloud auth application-default login           # Vertex AI uses your ADC credentials
# In .env:
#   LLM_PROVIDER=gemini
#   GENAI_BACKEND=vertex
#   GCP_PROJECT_ID=your-project-id
```

For Claude, set `LLM_PROVIDER=claude` and check that `CLAUDE_MODEL` is enabled in Vertex AI Model
Garden for your project and region.

---

## 3. Architecture

```
                         ┌────────────────────────── Google Cloud ──────────────────────────┐
  Browser                │                                                                  │
  (Google sign-in) ──────┼─► Cloud Run: agentflow-ui  (nginx + React bundle)                │
        │                │                                                                  │
        └── Bearer token ┼─► Cloud Run: agentflow-api (FastAPI)  ──────┬─► Cloud SQL       │
                         │      │  ▲                                    │   PostgreSQL 16   │
                         │      │  │ /internal/runs/{id}/execute        │   + pgvector      │
                         │      │  └── Cloud Tasks (OIDC) ◄─────────────┤                   │
                         │      │                                       ├─► Memorystore     │
                         │      ├─► Vertex AI: Gemini, Claude, embed ───┤   (rate limits)   │
                         │      │                                       ├─► Cloud Storage   │
                         │      └─► Secret Manager / Cloud Trace /      │   (uploads)       │
                         │          Cloud Logging (via OpenTelemetry)   │                   │
                         │                                              └─► Artifact Registry
                         │                                                  (images from Cloud Build)
                         └──────────────────────────────────────────────────────────────────┘

  Local: the same components run as: uvicorn (API) + vite (UI) + docker compose (Postgres, Redis).
```

### Request flow for a run

1. The UI calls `POST /api/v1/flows/{id}/runs` with the user's message.
2. The API checks ownership and the per-user rate limit, then stores a `Run` with `status=queued`.
3. The dispatcher starts the run:
   - `inline`: an asyncio task in the same process.
   - `cloud_tasks`: a Cloud Task that POSTs to `/internal/runs/{id}/execute` with an OIDC token
     for the invoker service account.
4. The executor walks the flow in order. Each node reads its input variable and writes its
   output variable. A trace entry is recorded per node, and each node runs in an OpenTelemetry span.
5. The executor stores `succeeded` or `failed`, plus the steps and output, on the `Run`.
6. The UI polls `GET /api/v1/runs/{id}` until the status is terminal.

The executor is **idempotent**: it only starts runs whose status is `queued`. A redelivered Cloud
Task therefore does nothing when the run is already finished.

---

## 4. Core concepts

### Flows and nodes

A **flow** is an ordered list of **nodes** (at most 50). The rules are checked on save, by the API
and again by the UI:

- Each node reads an **input variable** and writes an **output variable**. A variable must be
  written by an earlier node before it is read.
- Output variable names must be unique.
- Exactly **one** `output` node exists, and it is last.

| Node type | Reads | Writes | Configuration | What it does |
|---|---|---|---|---|
| `chat_input` | the run message | output var | none | Starts the flow with the user's message. |
| `llm` | input var | output var | `system_prompt` (≤ 4000 chars) | Calls the model on Vertex AI (Gemini or Claude). |
| `retriever` | input var (query) | output var | `collection`, `top_k` (1–20) | Finds the most similar chunks in the caller's collection. |
| `output` | input var | nothing | none | Its value is the run result. |

Example flow (JSON as stored by the API):

```json
{
  "name": "Policy search",
  "definition": {
    "nodes": [
      {"id": "in",  "type": "chat_input", "output_var": "question"},
      {"id": "kb",  "type": "retriever", "input_var": "question", "output_var": "context",
       "config": {"collection": "policies", "top_k": 4}},
      {"id": "out", "type": "output", "input_var": "context"}
    ]
  }
}
```

This flow returns the matching chunks as the result. An `llm` node only sees the variable it reads,
so a flow that answers a question from retrieved context needs a template node that combines the
question and the context into one prompt. That node is on the roadmap (section 10).

### Runs

A run has the status `queued` → `running` → `succeeded` or `failed`. Its `steps` array holds one
entry per node: `node_id`, `node_type`, `status`, `duration_ms` and a 300-character
`output_preview`. A failed run records the sanitized error only. Provider error text is written to
the logs, correlated by an error id, and is never returned to the user.

### Knowledge base (RAG)

- `POST /api/v1/collections/{collection}/documents` takes pasted text.
- `POST /api/v1/collections/{collection}/files` takes a `text/plain`, `text/markdown` or `text/csv`
  upload (5 MB, UTF-8).
- Text is split into 1000-character chunks with 150 characters of overlap, embedded with
  `EMBEDDING_MODEL`, and stored in `document_chunks` with the owner's email.
- Retrieval uses pgvector's cosine distance and only returns chunks owned by the caller.
- Uploaded files are also stored in Cloud Storage (`STORAGE_BACKEND=gcs`) for audit and
  re-indexing.

### Security model

**Roles.** Every user has one role. The Users section (admins only) sets them.

| Role | Can do |
|---|---|
| `platform_admin` | Everything, including managing users and reviewing any agent. The default account starts as admin. |
| `platform_user` | Create, edit and submit agents, add knowledge, guardrails and MCP connections. Approve their own submitted agents. Default for new users (`DEFAULT_USER_ROLE`). |

Submitting an agent sends it to the platform admins. Any admin, or the requester, can approve or reject it in Approvals. Admins listed in `ADMIN_EMAILS` always stay admins.

| Concern | How it is handled |
|---|---|
| Who is the user? | `AUTH_MODE=google`: the API verifies the Google ID token signature, audience, issuer and expiry, requires a verified email, and applies `ALLOWED_EMAIL_DOMAINS`. |
| Can users see each other's data? | Every flow, run and chunk has `owner_email`. Other users get **404** (not 403), so IDs cannot be probed. Admins (`ADMIN_EMAILS`) see everything. |
| Can the internal task endpoint be called from the internet? | The backend is public (it authenticates users itself), so `/internal/...` checks the **OIDC token of the invoker service account** on every call. |
| Are secrets in code or env? | No. `DATABASE_URL` and any API key come from Secret Manager in production. |
| PII to models | Redacted before model calls, when `PII_REDACTION_ENABLED=true`. |
| Errors | `log_error(...)` logs the traceback with an id. The user sees a sanitized message. No stack traces or provider messages leave the server. |
| Browser | Strict headers from nginx (`X-Frame-Options`, `nosniff`, `Referrer-Policy`). The API CORS list is explicit and `production` rejects `*`. |
| Container | Non-root user in the API image. Each Cloud Run service has its own identity. The API identity can read only the two secrets it needs, and it gets project roles only for the services it calls (see `bootstrap_gcp.sh`). |

---

## 5. Run it locally

### 5.1 Prerequisites

| Tool | Version | Used for |
|---|---|---|
| Python | 3.12+ | Backend |
| [uv](https://docs.astral.sh/uv/) | any recent | Creates the backend virtualenv (`make backend-install`) |
| Node.js | 20+ with npm | Frontend |
| Docker (with Compose v2) | recent | Local PostgreSQL with pgvector, and Redis |
| `make` | any | Shortcuts (optional; every command is also listed below) |
| gcloud CLI | recent | Only for real models or deployment |

### 5.2 Quick start (about 5 minutes)

```bash
cd gcp_claude
cp .env.example .env            # the defaults already run locally with the mock model

make infra-up                   # PostgreSQL 16 + pgvector on :5432, Redis on :6379
make backend-install            # creates backend/.venv and installs the API with dev tools
make backend-dev               # API on http://localhost:8080   (keep this terminal open)
```

`make backend-install` installs into whatever environment `VIRTUAL_ENV` points at if one is active
in your shell. Run `deactivate` (or `unset VIRTUAL_ENV`) first, or use the explicit commands in
[5.3](#53-without-make).

In a second terminal:

```bash
cd gcp_claude
make frontend-install           # npm ci
make frontend-dev               # UI on http://localhost:5173
```

Open <http://localhost:5173>. You are signed in as `DEV_USER_EMAIL` (dev auth mode). Then:

1. Click **New flow**. The starter flow is *Chat input → Model → Output*.
2. Click **Save flow**, then **Run this flow**.
3. Type a message, for example `My email is jane@example.com`, and click **Run**. The result shows
   `[mock-llm] My email is [EMAIL_REDACTED]`. That shows the PII guardrail working end to end.

Interactive API docs are at <http://localhost:8080/docs> (available outside production).

### 5.3 Without make

```bash
docker compose up -d postgres redis

cd backend
uv venv --clear --python 3.12 .venv
uv pip install --python .venv/bin/python -e ".[dev]"
.venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port 8080

cd ../frontend
npm ci
npm run dev
```

The backend finds `../.env` itself, so you can run commands from any directory inside `backend/`.

### 5.4 Everything in containers

This runs the same images that Cloud Run runs:

```bash
make stack-up                   # builds backend and frontend images, starts them with Postgres and Redis
# UI:  http://localhost:8081      API: http://localhost:8080
make stack-down
```

Port 8081 is used because the containerized UI is wired to the containerized API on 8080. The
compose file overrides `DATABASE_URL`, `REDIS_URL` and `CORS_ORIGINS` for the container network.

### 5.5 Local Google sign-in (optional, same as production)

1. In Google Cloud Console, create an OAuth client ID of type **Web application** and add
   `http://localhost:5173` under **Authorized JavaScript origins**.
2. In `.env`, set:
   ```
   AUTH_MODE=google
   GOOGLE_CLIENT_ID=<client id>
   UI_AUTH_MODE=google
   UI_GOOGLE_CLIENT_ID=<same client id>
   ```
3. Restart `make backend-dev` and reload the UI. You will see the Google sign-in button.

### 5.6 Tests

```bash
make test                       # backend (pytest) + frontend (vitest), no cloud or DB needed
make backend-test-integration   # PostgreSQL + pgvector: ingestion and retrieval (needs `make infra-up`)
make frontend-build             # strict TypeScript check + production bundle
```

Test layout:

| File | What it covers | Needs |
|---|---|---|
| `backend/tests/test_unit.py` | Config rules, flow validation, PII redaction, chunking | nothing |
| `backend/tests/test_auth.py` | Google token handling, domain allowlist, Cloud Tasks invoker check (verifier mocked) | nothing |
| `backend/tests/test_llm.py` | Gemini and embedding client wiring (stub SDK) | nothing |
| `backend/tests/test_api.py` | Full HTTP flows, runs, redaction, sanitized failures | SQLite (automatic) |
| `backend/tests/test_integration_postgres.py` | RAG round trip and owner isolation on real pgvector | `TEST_DATABASE_URL` |
| `frontend/src/lib/nodeTypes.test.ts` | Client-side flow rules | nothing |

Lint: `cd backend && .venv/bin/ruff check app tests` (the project config is in `pyproject.toml`).

---

## 6. API reference

All endpoints under `/api/v1` require authentication:

- `AUTH_MODE=dev`: header `X-Dev-User: you@example.com` (optional, defaults to `DEV_USER_EMAIL`).
- `AUTH_MODE=google`: header `Authorization: Bearer <Google ID token>`.

| Method and path | Purpose | Success |
|---|---|---|
| `GET /healthz` | Liveness (no dependencies touched) | 200 |
| `GET /readyz` | Readiness (database ping) | 200, or 503 |
| `GET /api/v1/flows` | Your flows (all flows for admins) | 200 |
| `POST /api/v1/flows` | Create a flow | 201 |
| `GET /api/v1/flows/{id}` | Read one flow | 200 |
| `PUT /api/v1/flows/{id}` | Update name, description or definition | 200 |
| `DELETE /api/v1/flows/{id}` | Delete a flow and its runs | 204 |
| `POST /api/v1/flows/{id}/runs` | Start a run. Body `{"message": "..."}` | 202 (poll for the result) |
| `GET /api/v1/flows/{id}/runs` | Last 50 runs of a flow | 200 |
| `GET /api/v1/runs/{id}` | Run status, output, steps, error | 200 |
| `POST /api/v1/collections/{name}/documents` | Ingest pasted text `{"source","text"}` | 201 |
| `POST /api/v1/collections/{name}/files` | Ingest an uploaded text file (multipart `file`) | 201 |
| `POST /internal/runs/{id}/execute` | Cloud Tasks target. Not for other callers | 200 |

Errors use `{"detail": "..."}`. Validation errors (422) give a list of `{loc, msg, type}`.
Unknown or foreign flow and run IDs return 404.

Example session against a local API:

```bash
H='X-Dev-User: you@example.com'
curl -s -X POST localhost:8080/api/v1/collections/policies/documents \
  -H "$H" -H 'Content-Type: application/json' \
  -d '{"source":"refunds.md","text":"Refunds are issued within 14 days of purchase."}'

curl -s -X POST localhost:8080/api/v1/flows -H "$H" -H 'Content-Type: application/json' -d @flow.json
curl -s -X POST localhost:8080/api/v1/flows/<flow-id>/runs -H "$H" \
  -H 'Content-Type: application/json' -d '{"message":"How long do refunds take?"}'
curl -s localhost:8080/api/v1/runs/<run-id> -H "$H"
```

---

## 7. Deploy to Google Cloud

The deployment is scripted. Every script supports `DRY_RUN=1`, which prints each `gcloud` command
without running it. Use that to review a change before it touches your project.

### 7.1 What gets created

| Resource | Name (default) | Purpose |
|---|---|---|
| APIs | run, cloudbuild, artifactregistry, secretmanager, sqladmin, aiplatform, cloudtasks, storage, cloudtrace, logging, iam, vpcaccess, redis | Enabled by `bootstrap_gcp.sh` |
| Artifact Registry | `agentflow` (Docker) | API and UI images |
| Service accounts | `agentflow-api-sa`, `agentflow-ui-sa`, `agentflow-tasks-invoker` | One identity per workload |
| Cloud Run | `agentflow-api`, `agentflow-ui` | The two services |
| Cloud SQL | `<CLOUD_SQL_CONNECTION_NAME>`, PostgreSQL 16, database `agentflow`, user `agentflow` | Data plus pgvector |
| Cloud Storage | `<project>-agentflow-uploads` | Uploaded source files |
| Secret Manager | `agentflow-database-url`, `agentflow-gemini-api-key` (placeholder) | Secrets mounted into Cloud Run |
| Cloud Tasks | queue `agentflow-runs` | Run dispatch with retries (5 attempts, backoff to 300 s) |
| Memorystore + VPC connector | `agentflow-cache`, `agentflow-connector` | Optional. Rate limiting. Off unless `CREATE_MEMORYSTORE=true` |

### 7.2 Prerequisites

- A Google Cloud project with **billing enabled**.
- The `gcloud` CLI, logged in with a user who can enable APIs and manage IAM (for a first
  deployment, the Owner role is simplest):
  ```bash
  gcloud auth login
  gcloud auth application-default login
  ```
- Docker is **not** needed for deployment. Cloud Build builds the images.

### 7.3 Step 1: fill in the deployment keys in `.env`

Set these in `.env`. The values below are examples:

```
GCP_PROJECT_ID=my-project-id
GCP_REGION=us-central1
CLOUD_SQL_CONNECTION_NAME=my-project-id:us-central1:agentflow-pg

LLM_PROVIDER=gemini             # or claude
GENAI_BACKEND=vertex            # production always uses Vertex AI (set by deploy.sh anyway)
GCP_PROJECT_ID=my-project-id

AUTH_MODE=google                # deploy.sh forces this; set it here so local matches production
GOOGLE_CLIENT_ID=<your client id>
UI_GOOGLE_CLIENT_ID=<your client id>
ALLOWED_EMAIL_DOMAINS=example.com
ADMIN_EMAILS=you@example.com
```

Leave `MEMORYSTORE_REDIS_URL` empty for now. Rate limiting is then disabled in production, and
the logs say so. Add Redis later (step 7.7).

### 7.4 Step 2: one-time project bootstrap

```bash
DRY_RUN=1 ./deploy/scripts/bootstrap_gcp.sh   # review the commands first
./deploy/scripts/bootstrap_gcp.sh             # apply (safe to re-run)
```

This is the step that takes the longest, because Cloud SQL instance creation takes several minutes. The script
also creates the database user and writes its generated password to Secret Manager. Nothing in
the repository stores that password.

Enabling pgvector runs `deploy/sql/init.sql.template` through `gcloud sql import sql`. Cloud SQL
users are not superusers, so a direct `CREATE EXTENSION` from the app would fail. The import runs
with the privileges Cloud SQL needs.

### 7.5 Step 3: Google OAuth client (manual)

`gcloud` cannot create the OAuth client, so do this in the console:

1. **Google Auth Platform → Branding**: set the app name and support email.
2. **Audience**: choose *Internal* for a Google Workspace organisation, or *External* with test
   users during development.
3. **Clients → Create client → Web application.** Copy the client ID into `GOOGLE_CLIENT_ID` and
   `UI_GOOGLE_CLIENT_ID` in `.env`.
4. Leave **Authorized JavaScript origins** for now. You add the UI URL in step 7.6.

### 7.6 Step 4: build and deploy

```bash
DRY_RUN=1 ./deploy/scripts/deploy.sh all    # review
./deploy/scripts/deploy.sh all              # build with Cloud Build, deploy API and UI, wire URLs
```

What the script does, in order:

1. Checks the configuration (refuses `LLM_PROVIDER=mock`, and requires the database secret).
2. Runs `gcloud builds submit` with `deploy/cloudbuild.yaml`, which builds
   `api:<tag>` and `ui:<tag>` into Artifact Registry. `.gcloudignore` keeps `.env` out of the
   upload.
3. Deploys `agentflow-api` with the service account, Cloud SQL attachment, 1 vCPU / 1 GiB,
   `--no-cpu-throttling` (needed for in-process background runs), concurrency 40 and a 900-second
   timeout. Environment variables and secrets come from `.env` through `env_to_cloudrun.py`.
4. Grants the invoker service account `roles/run.invoker` on the API, so Cloud Tasks can call the
   internal endpoint.
5. Checks `/readyz` on the API.
6. Deploys `agentflow-ui` with `UI_API_BASE_URL` set to the API URL.
7. Updates the API with `BACKEND_PUBLIC_URL` and `CORS_ORIGINS` set to the real URLs. The URLs
   are only known after the first deploy.

Target a single service with `./deploy/scripts/deploy.sh backend` or `... ui`.

### 7.7 Step 5: finish the OAuth origin and verify

1. Copy the UI URL printed at the end of the deploy. Add it to **Authorized JavaScript origins**
   on the OAuth client.
2. Open the UI URL and sign in with an allowed account. Create a flow, run it, and check the
   result.
3. Check the API:
   ```bash
   curl -s https://<api-url>/readyz                       # {"status":"ready"}
   gcloud run services logs read agentflow-api --region us-central1 --limit 50
   ```
   Traces appear in **Cloud Trace** and structured logs in **Cloud Logging**, under the
   `agentflow-api` service.

### 7.8 Optional: Memorystore for rate limiting

```bash
CREATE_MEMORYSTORE=true ./deploy/scripts/bootstrap_gcp.sh
```

The script prints the Redis address. In `.env`, set `MEMORYSTORE_REDIS_URL=redis://<ip>:6379/0`
and `VPC_CONNECTOR=agentflow-connector`, then run `./deploy/scripts/deploy.sh backend`.

Memorystore is only reachable inside a VPC, so Cloud Run needs the connector. Without it,
rate limiting is off and the logs say so.

### 7.9 Redeploying, rolling back, and tearing down

```bash
./deploy/scripts/deploy.sh all                         # new code or .env changes

# Roll back the API: list revisions, then send 100% of traffic to the one you want
gcloud run revisions list --service agentflow-api --region us-central1
gcloud run services update-traffic agentflow-api --region us-central1 \
  --to-revisions=<previous-revision-name>=100

# Remove everything created by this guide (irreversible; deletes data)
gcloud run services delete agentflow-api --region us-central1 --quiet
gcloud run services delete agentflow-ui  --region us-central1 --quiet
gcloud sql instances patch agentflow-pg --no-deletion-protection && \
  gcloud sql instances delete agentflow-pg --quiet
```

### 7.10 Costs and sizing

The main cost drivers are Cloud SQL (an always-on instance; the default tier is
`db-custom-1-3840`), Memorystore if you enable it, and Vertex AI token usage. Cloud Run is
billed per request and per instance-second. Set `*_MIN_INSTANCES=0` to scale to zero, and
`BACKEND_MAX_INSTANCES` to cap spend. Check current prices in the Google Cloud pricing calculator.

---

## 8. Production checklist and operations

Before you go live, check these items:

- [ ] `AUTH_MODE=google`, and `ALLOWED_EMAIL_DOMAINS` is set to your organisation's domains.
- [ ] `ADMIN_EMAILS` lists only people who should see every flow.
- [ ] `LLM_PROVIDER` is `gemini` or `claude`, and the model IDs are enabled in your project.
- [ ] Cloud SQL has backups and deletion protection (set by bootstrap). Test a restore once.
- [ ] `DB_AUTO_CREATE` is a conscious decision. It creates missing tables at startup but never
      alters existing ones. Before the first schema change, add Alembic (see section 10).
- [ ] Memorystore is enabled if you want per-user rate limiting. Otherwise, document the risk.
- [ ] Logs: `LOG_FORMAT=json`. Create a log-based alert on `severity>=ERROR`.
- [ ] Traces: `OTEL_EXPORTER=gcp`. Check Cloud Trace shows `node.llm` spans.
- [ ] Budget alert on the project (Billing → Budgets & alerts).
- [ ] Add a Cloud Armor or load-balancer layer if you need WAF rules or a custom domain.
- [ ] Add a CSP header to nginx once the Google sign-in and API origins are final.

Operational notes:

- **Scaling.** Each API instance serves up to 40 concurrent requests. A run spends most of its
  time waiting on model and database calls, so instances scale mainly by memory and concurrency.
  `--no-cpu-throttling` keeps CPU allocated after a response is sent, which lets inline background
  runs finish.
- **Long runs.** Cloud Tasks dispatches with retries, and the executor is idempotent, so a
  retried delivery of a finished run does nothing. A run that crashes mid-way stays `running`.
  A reaper job for stale runs is a worthwhile addition.
- **Logs and traces.** The code does not log document text or prompts. Error logs carry ids and
  node types. Step previews stored with a run are truncated to 300 characters.

---

## 9. Extending the code

### Add a node type

1. **Backend schema.** In `backend/app/schemas.py`, add the name to `NodeType`, add a config model
   to `NODE_CONFIG_MODELS`, and set `needs_input`/`needs_output` in `NodeDef` if the wiring is
   new.
2. **Executor.** In `backend/app/services/executor.py`, add a branch to `_run_node`. Use `llm` for
   model access and `session` for database access. Keep side effects behind a service module.
3. **Frontend catalogue.** In `frontend/src/lib/nodeTypes.ts`, add an entry to `NODE_TYPES` and
   any config validation to `validateNodeConfig`. Add a test in `nodeTypes.test.ts`.
4. **Editor fields.** In `frontend/src/components/NodeEditor.tsx`, add the config inputs.
5. **Tests.** Add an API test in `backend/tests/test_api.py` with a flow that uses the node.

### Add a model provider

Implement `LLMClient` (`generate` and `embed`) in `backend/app/services/llm.py`, add it to
`build_llm_client`, and add the provider to `Settings.llm_provider` and the validator. Embeddings
must produce `EMBEDDING_DIM` values, because the database column is fixed in size.

### Change the database schema

Add the change to `backend/app/models.py`. Until Alembic is added, `DB_AUTO_CREATE` only creates
missing tables. A new column on an existing table needs a manual `ALTER TABLE`, or Alembic.

---

## 10. Scope: what is ported, what is not

The original platform (`tiger_agentflow`) has many more modules. This repository deliberately
ships a smaller, production-shaped core first. The table lists the mapping.

| Original module | Status here | GCP service / approach | Where |
|---|---|---|---|
| PostgreSQL (platform DB) | ✅ Ported | Cloud SQL for PostgreSQL 16 | `db.py`, `deploy/sql` |
| pgvector / vector stores | ✅ Ported (pgvector only) | pgvector on Cloud SQL | `services/knowledge.py` |
| Agent architecture → ADK graph | ✅ Saving a draft compiles the canvas into an ADK graph: chained steps run in order, branches run in parallel, and cycles are refused | `services/adk_graph.py`, `services/adk_draft.py` |
| Redis (cache, Casbin watcher) | ✅ Partly (rate limiting) | Memorystore for Redis | `services/cache.py` |
| S3 / Blob / GCS storage | ✅ Ported | Cloud Storage | `services/storage.py` |
| LiteLLM via `ta_ai` (LLMs) | ✅ Ported | Vertex AI: Gemini (google-genai), Claude (AnthropicVertex) | `services/llm.py` |
| Embeddings (`ta_ai`) | ✅ Ported | Vertex AI `text-embedding-005` | `services/llm.py` |
| LangGraph agent executor | ⚠️ Simplified | Linear node executor (no DAG, no tool loop) | `services/executor.py` |
| Chat Input / Model / Knowledge Retriever / Output nodes | ✅ Ported | Node types in the executor | `schemas.py`, `executor.py` |
| Agent node with tools | ❌ Not yet | Vertex AI function calling inside the `llm` node | roadmap |
| Web Search node | ❌ Not yet | Gemini with Google Search grounding | roadmap |
| SQL Retriever node | ❌ Not yet | Cloud SQL / AlloyDB, read-only role | roadmap |
| Guardrails service | ⚠️ Partly | PII redaction runs on every model call. Model Armor and Sensitive Data Protection templates can be combined and saved, but agents do not enforce them yet | `services/guardrails.py`, `routers/guardrails.py` |
| MCP client | ⚠️ Connect and list tools | Streamable HTTP handshake. Auth: none, Google ID token, bearer token or API key header, with secrets read from Secret Manager. Agents do not call the tools yet | `services/mcp_client.py`, `services/secrets.py` |
| Code sandbox (`sandbox_executor`) | ❌ Not yet | Cloud Run jobs with no network egress | roadmap |
| Human-in-the-loop / approvals | ❌ Not yet | Persist paused state, resume via Cloud Tasks | roadmap |
| Scheduled triggers / webhooks | ❌ Not yet | Cloud Scheduler → authenticated `/internal` endpoint | roadmap |
| Evaluation (`af_evaluation`) | 🟡 Criteria and rubrics from the installed ADK. Scoring not wired yet | `GET /api/v1/eval-metrics`, `pages/studio/CriteriaPanel.tsx` |
| Auth (Azure AD / Okta) | ⚠️ Google only | Google sign-in. Identity Platform if you need more IdPs | `auth.py` |
| RBAC | ✅ `platform_admin`, `platform_user` | Roles are stored in the Users section. Admins can be pinned in `ADMIN_EMAILS`. | `auth.py`, `routers/users.py` |
| Observability (SigNoz, App Insights) | ✅ Ported | OpenTelemetry → Cloud Trace, Cloud Logging | `observability.py`, `logging_setup.py` |
| Observability (OTLP traces, Cloud Trace) | 🟡 OTLP ingest at `/v1/traces` (protobuf and JSON), trace and summary queries, Cloud Trace listing when `GCP_PROJECT_ID` is set | `routers/observability.py`, `services/telemetry.py`, `routers/gcp.py` |
| Infra (Terraform, AWS/Azure pipelines) | ⚠️ gcloud scripts | Terraform is the natural next step | `deploy/scripts` |
| Frontend (MUI, Redux, xyflow canvas) | ✅ Agent canvas on @xyflow/react, like the Tiger AgentFlow canvas. Positions, edges and Start/Stop markers are saved with the draft | `frontend/src/components/flow/`, `pages/studio/AgentCanvasPage.tsx` |
| Alembic migrations | ❌ Not yet | Add Alembic and set `DB_AUTO_CREATE=false` | roadmap |

Recommended order for the next work:

1. Alembic migrations, then `DB_AUTO_CREATE=false` in production.
2. Agent node with tool calling (Vertex AI function calling).
3. Terraform for the bootstrap steps, once the shape stops changing.
4. Cloud Scheduler triggers, then human-in-the-loop approvals.

---

## 11. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Backend exits with `Invalid configuration: …` | A `.env` rule is violated | The message names the keys. Fix them in `.env`. |
| `make backend-dev` fails with connection refused to 5432 | Postgres is not running | `make infra-up`, then `docker compose ps` should show `healthy`. |
| `.venv/bin/uvicorn: No such file or directory` (`make backend-dev`) | `backend/.venv` exists but has no packages installed | `make backend-install`. If it still fails, run `deactivate`, then `make backend-install` again. |
| `[Errno 98] Address already in use` on port 8080 | Another API process is still running | Find it with `ss -ltnp \| grep :8080` and stop it, or start the API on another port. |
| `readyz` returns 503 | Database unreachable | Check `DATABASE_URL`. On Cloud Run, check the `--add-cloudsql-instances` attachment and the `cloudsql.client` role. |
| `type "vector" does not exist` | pgvector not enabled | Locally use the `pgvector/pgvector` image (compose does this). In Cloud SQL, rerun `bootstrap_gcp.sh`. |
| Ingestion fails with a dimension error | `EMBEDDING_DIM` does not match the table | Use the same value for the model and the column. Changing it needs a new table. |
| `401 Invalid or expired token` | Stale Google token, or wrong `GOOGLE_CLIENT_ID` | Sign in again. The client ID must match `GOOGLE_CLIENT_ID` on the API. |
| `403 Your email domain is not allowed` | `ALLOWED_EMAIL_DOMAINS` | Add the domain or clear the setting. |
| Browser shows a CORS error | UI origin not in `CORS_ORIGINS` | The deploy wires this automatically. Locally, add the origin to `.env` and restart the API. |
| Run stays `queued` on Cloud Run | Cloud Tasks cannot call the API | Check the queue, `roles/run.invoker` for `agentflow-tasks-invoker` on the API, and `BACKEND_PUBLIC_URL`. |
| `403 Caller is not the Cloud Tasks invoker` in logs | Token audience or identity mismatch | `BACKEND_PUBLIC_URL` must equal the exact Cloud Run URL (no trailing slash). |
| Run fails with `Something went wrong … (ref …)` | Provider or code error | Search the Cloud Logging for the `error_id=<ref>` value to see the full traceback. |
| `Claude` calls return 404 or permission errors | Model not enabled, or wrong region | Enable it in Vertex AI Model Garden, and check `CLAUDE_MODEL` and `GCP_LOCATION`. |
| Deploy fails on `agentflow-database-url not found` | Bootstrap not run | `./deploy/scripts/bootstrap_gcp.sh`. |
| `column ... does not exist` on `mcp_servers` after an update | Table predates the MCP client columns | Restart the API. `init_db` adds the missing columns on Postgres. |
| UI shows stale configuration after a change | Browser cache on `config.js` | `config.js` is served with `no-store`. Hard-reload once. |

Useful commands:

```bash
make help                                             # every developer command
docker compose logs -f postgres                       # database logs
gcloud run services logs tail agentflow-api --region us-central1
gcloud run services describe agentflow-api --region us-central1 --format='value(status.url)'
```
