#!/usr/bin/env bash
# Run the FastAPI backend dev server (auto-reload) on :8000.
# Infra (PostgreSQL + MinIO) must already be up via cloud_agent_start.sh.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/cloud_agent_env.sh
source "$SCRIPT_DIR/cloud_agent_env.sh"

exec "$TENDER_REPO/.venv/bin/uvicorn" app.main:app \
  --app-dir "$TENDER_REPO/backend" \
  --host 0.0.0.0 --port 8000 --reload
