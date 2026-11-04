#!/usr/bin/env python3
"""Translate the root .env into gcloud flags for one Cloud Run service.

Prints one gcloud flag per line (empty output lines are never printed):

    --set-env-vars=^|^KEY=value|KEY2=value2
    --set-secrets=KEY=secret-name:latest,KEY2=other-secret:latest

The custom "^|^" delimiter is used so values may contain commas (CORS origins,
domain lists) and "@" (email addresses).

Rules:
  * backend gets every non-UI_ key; ui gets only UI_* keys.
  * Deployment-only keys (region, service names, Cloud SQL tier...) are never sent.
  * Keys in SECRET_KEYS are never sent as plain text. They are mounted from Secret
    Manager, so the local value in .env (for example a localhost DATABASE_URL) is ignored.
  * Empty values are skipped, so an unset key keeps the application default.
  * --override KEY=VALUE replaces a value (used by deploy.sh for production URLs).
  * MEMORYSTORE_REDIS_URL (deploy-only) becomes REDIS_URL. The local REDIS_URL is never
    sent, because localhost means nothing inside Cloud Run.
  * GEMINI_API_KEY is only mounted when GENAI_BACKEND is api_key.

Usage:
    env_to_cloudrun.py --env-file ../../.env --service backend \
        --override APP_ENV=production --override CORS_ORIGINS=https://ui.example.com
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Deployment tooling keys. Read by the scripts, never sent to Cloud Run.
DEPLOY_ONLY_KEYS = {
    "GCP_REGION",
    "ARTIFACT_REGISTRY_REPO",
    "BACKEND_SERVICE_NAME",
    "FRONTEND_SERVICE_NAME",
    "BACKEND_SERVICE_ACCOUNT",
    "FRONTEND_SERVICE_ACCOUNT",
    "CLOUD_SQL_CONNECTION_NAME",
    "CLOUD_SQL_TIER",
    "CLOUD_SQL_DB",
    "CLOUD_SQL_USER",
    "VPC_CONNECTOR",
    "MEMORYSTORE_REDIS_URL",  # copied into REDIS_URL for the service; never sent as its own key
    "BACKEND_MIN_INSTANCES",
    "BACKEND_MAX_INSTANCES",
    "BACKEND_CPU",
    "BACKEND_MEMORY",
    "FRONTEND_MIN_INSTANCES",
    "FRONTEND_MAX_INSTANCES",
}

# Secret key -> Secret Manager secret name (backend only). Secret names are created by
# bootstrap_gcp.sh; deploy.sh syncs GEMINI_API_KEY from .env when it is set there.
SECRET_KEYS = {
    "DATABASE_URL": "agentflow-database-url",
    "GEMINI_API_KEY": "agentflow-gemini-api-key",
}

DELIMITER = "|"


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        # Strip an inline comment only when it is preceded by whitespace.
        value = value.split(" #", 1)[0].strip()
        values[key.strip()] = value
    return values


def build_flags(values: dict[str, str], service: str) -> list[str]:
    env_pairs: dict[str, str] = {}
    secrets: dict[str, str] = {}
    values = dict(values)
    # The local REDIS_URL (localhost) is unreachable from Cloud Run. Without Memorystore
    # the variable is left empty, which disables rate limiting instead of failing every run.
    values["REDIS_URL"] = values.get("MEMORYSTORE_REDIS_URL", "")

    for key, value in values.items():
        if key in DEPLOY_ONLY_KEYS:
            continue
        if service == "backend" and key.startswith("UI_"):
            continue
        if service == "ui" and not key.startswith("UI_"):
            continue
        if service == "backend" and key in SECRET_KEYS:
            needs_gemini_key = values.get("GENAI_BACKEND", "api_key") == "api_key"
            if key == "DATABASE_URL" or (key == "GEMINI_API_KEY" and needs_gemini_key and value):
                secrets[key] = f"{SECRET_KEYS[key]}:latest"
            continue
        if value == "":
            continue
        env_pairs[key] = value

    flags: list[str] = []
    if env_pairs:
        for key, value in env_pairs.items():
            if DELIMITER in value:
                raise SystemExit(f"{key} contains '{DELIMITER}', which is reserved by this script")
        pairs = DELIMITER.join(f"{k}={v}" for k, v in env_pairs.items())
        flags.append(f"--set-env-vars=^{DELIMITER}^{pairs}")
    if secrets:
        flags.append("--set-secrets=" + ",".join(f"{k}={v}" for k, v in secrets.items()))
    return flags


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument("--service", required=True, choices=["backend", "ui"])
    parser.add_argument("--override", action="append", default=[], metavar="KEY=VALUE")
    args = parser.parse_args()

    if not args.env_file.is_file():
        sys.exit(f"env file not found: {args.env_file}")

    values = parse_env_file(args.env_file)
    for item in args.override:
        key, sep, value = item.partition("=")
        if not sep:
            sys.exit(f"--override must be KEY=VALUE, got: {item}")
        values[key] = value

    for flag in build_flags(values, args.service):
        print(flag)


if __name__ == "__main__":
    main()
