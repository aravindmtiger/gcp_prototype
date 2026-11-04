# Common developer tasks. Run `make help` for the list.
# All application configuration lives in ./.env (copy it from .env.example first).

SHELL := /bin/bash
BACKEND := backend
FRONTEND := frontend
PY := $(BACKEND)/.venv/bin

.PHONY: help env infra-up infra-down backend-install backend-dev backend-test backend-test-integration \
        frontend-install frontend-dev frontend-test frontend-build test stack-up stack-down deploy

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-28s\033[0m %s\n", $$1, $$2}'

env: ## Create .env from the template if it does not exist
	@test -f .env || cp .env.example .env && echo ".env ready"

infra-up: env ## Start local PostgreSQL (pgvector) and Redis
	docker compose up -d postgres redis

infra-down: ## Stop local infrastructure (keeps data volume)
	docker compose down

backend-install: ## Create backend/.venv and install the API with dev tools
	cd $(BACKEND) && uv venv --clear --python 3.12 .venv && uv pip install --python .venv/bin/python -e ".[dev]"

backend-dev: ## Run the API with auto-reload on http://localhost:8080
	cd $(BACKEND) && .venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port 8080

backend-test: ## Unit and API tests (SQLite, no cloud calls)
	cd $(BACKEND) && .venv/bin/pytest

backend-test-integration: ## Tests against local PostgreSQL + pgvector (run infra-up first)
	cd $(BACKEND) && TEST_DATABASE_URL=postgresql+asyncpg://agentflow:agentflow@localhost:5432/agentflow .venv/bin/pytest tests/test_integration_postgres.py

frontend-install: ## Install UI dependencies
	cd $(FRONTEND) && npm ci

frontend-dev: ## Run the UI with hot reload on http://localhost:5173
	cd $(FRONTEND) && npm run dev

frontend-test: ## UI unit tests
	cd $(FRONTEND) && npm test

frontend-build: ## Type-check and build the UI bundle
	cd $(FRONTEND) && npm run build

test: backend-test frontend-test ## Run all fast tests

stack-up: env ## Run infrastructure + API + UI as containers
	docker compose --profile app up --build -d

stack-down: ## Stop all local containers
	docker compose --profile app down

deploy: ## Deploy to Cloud Run (see README, section "Deploy to Google Cloud")
	./deploy/scripts/deploy.sh all
