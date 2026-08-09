#!/usr/bin/env bash
# Run the Vite frontend dev server on :3000 (proxies /api -> :8000).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/cloud_agent_env.sh
source "$SCRIPT_DIR/cloud_agent_env.sh"

cd "$TENDER_REPO/frontend"
exec npm run dev -- --host 0.0.0.0 --port 3000
