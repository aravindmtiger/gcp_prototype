#!/bin/sh
# Runs before nginx starts (official nginx image hook). Writes window.__APP_CONFIG__
# from UI_* environment variables so one build serves every environment.
set -eu

for name in UI_API_BASE_URL UI_AUTH_MODE UI_GOOGLE_CLIENT_ID UI_DEV_USER; do
    eval "value=\${$name:-}"
    case "$value" in
        *\"*|*\\*)
            echo "ERROR: $name must not contain quotes or backslashes" >&2
            exit 1
            ;;
    esac
done

cat > /usr/share/nginx/html/config.js <<JS
window.__APP_CONFIG__ = {
  "UI_API_BASE_URL": "${UI_API_BASE_URL:-}",
  "UI_AUTH_MODE": "${UI_AUTH_MODE:-dev}",
  "UI_GOOGLE_CLIENT_ID": "${UI_GOOGLE_CLIENT_ID:-}",
  "UI_DEV_USER": "${UI_DEV_USER:-}"
};
JS
echo "runtime config written: API=${UI_API_BASE_URL:-<unset>} AUTH=${UI_AUTH_MODE:-dev}"
