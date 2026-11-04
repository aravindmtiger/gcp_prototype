#!/usr/bin/env bash
# Shared helpers for bootstrap_gcp.sh and deploy.sh. Sourced, not executed.
#
# DRY_RUN=1 prints every gcloud command instead of running it, which is the safe way
# to review a deployment before it touches a project.

set -euo pipefail

DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ROOT_DIR="$(cd "$DEPLOY_DIR/.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env}"
DRY_RUN="${DRY_RUN:-0}"

log() { printf '\033[36m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[33mWARN:\033[0m %s\n' "$*" >&2; }
die() { printf '\033[31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

# Read one KEY from the .env file without sourcing it (values may contain & ? etc.).
env_get() {
    local key="$1" line
    line="$(grep -E "^${key}=" "$ENV_FILE" | tail -n 1 || true)"
    line="${line#"${key}="}"
    line="${line%%" #"*}"
    printf '%s' "$line" | sed -e 's/[[:space:]]*$//'
}

require_env() {
    local key value missing=0
    for key in "$@"; do
        value="$(env_get "$key")"
        if [[ -z "$value" ]]; then
            warn "$key is empty in $ENV_FILE"
            missing=1
        fi
    done
    [[ $missing -eq 0 ]] || die "fill in the keys above in $ENV_FILE and retry"
}

# Run a command, or print it when DRY_RUN=1.
run() {
    if [[ "$DRY_RUN" == "1" ]]; then
        printf '   [dry-run] %s\n' "$*"
        return 0
    fi
    "$@"
}

# Like run, but discards stdout in real runs. The dry-run line is still printed.
run_quiet() {
    if [[ "$DRY_RUN" == "1" ]]; then
        printf '   [dry-run] %s\n' "$*"
        return 0
    fi
    "$@" >/dev/null
}

# Like run, but keeps stdout (for commands whose output is needed).
capture() {
    if [[ "$DRY_RUN" == "1" ]]; then
        printf 'DRY-RUN-VALUE'
        return 0
    fi
    "$@"
}

check_gcloud() {
    command -v gcloud >/dev/null || die "gcloud CLI not found. Install: https://cloud.google.com/sdk/docs/install"
    [[ "$DRY_RUN" == "1" ]] && return 0
    local account
    account="$(gcloud config get-value account 2>/dev/null || true)"
    [[ -n "$account" ]] || die "not logged in. Run: gcloud auth login && gcloud auth application-default login"
    log "gcloud account: $account"
}

# Returns success if the resource exists (always "no" in dry-run so creates are printed).
exists() {
    [[ "$DRY_RUN" == "1" ]] && return 1
    "$@" >/dev/null 2>&1
}

# create_secret NAME VALUE: creates the secret if needed and adds VALUE as a new version.
create_secret() {
    local name="$1" value="$2"
    if ! exists gcloud secrets describe "$name"; then
        run gcloud secrets create "$name" --replication-policy=automatic
    fi
    if [[ "$DRY_RUN" == "1" ]]; then
        printf '   [dry-run] add a new version to secret %s (value not printed)\n' "$name"
        return 0
    fi
    printf '%s' "$value" | gcloud secrets versions add "$name" --data-file=- >/dev/null
}
