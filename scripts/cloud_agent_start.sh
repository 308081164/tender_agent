#!/usr/bin/env bash
# Per-boot startup for the Cloud Agent dev environment. Brings the full stack up
# in the background and returns: PostgreSQL, MinIO, the FastAPI backend (:8000)
# and the Vite frontend (:3000). Idempotent and safe to run repeatedly.
#
# For interactive/foreground use you can instead run scripts/backend_dev.sh and
# scripts/frontend_dev.sh in separate terminals.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/cloud_agent_env.sh
source "$SCRIPT_DIR/cloud_agent_env.sh"

echo "==> Starting PostgreSQL"
if "$PG_BINDIR/pg_ctl" -D "$PGDATA" status >/dev/null 2>&1; then
  echo "PostgreSQL already running"
else
  # Clear any stale pid/socket from an unclean shutdown before starting.
  rm -f "$PGDATA/postmaster.pid" 2>/dev/null || true
  "$PG_BINDIR/pg_ctl" -D "$PGDATA" -l "$TENDER_RUNTIME/pg.log" \
    -o "-p $PGPORT -k /tmp" -w start
fi

echo "==> Starting MinIO"
if curl -fsS "http://$MINIO_ENDPOINT/minio/health/live" >/dev/null 2>&1; then
  echo "MinIO already running"
else
  mkdir -p "$MINIO_DATA"
  nohup env MINIO_ROOT_USER="$MINIO_ROOT_USER" MINIO_ROOT_PASSWORD="$MINIO_ROOT_PASSWORD" \
    "$TENDER_BIN/minio" server "$MINIO_DATA" \
    --address :9000 --console-address :9001 \
    >"$TENDER_RUNTIME/minio.log" 2>&1 &
  for _ in $(seq 1 30); do
    if curl -fsS "http://$MINIO_ENDPOINT/minio/health/live" >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done
fi

# Wait for readiness so dependent services can rely on both being up.
for _ in $(seq 1 30); do
  if PGPASSWORD=tender123 psql -h 127.0.0.1 -p "$PGPORT" -U tender \
      -d tender_agent -c "SELECT 1" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

echo "==> Infrastructure ready (PostgreSQL :$PGPORT, MinIO :9000 / console :9001)"

port_in_use() { curl -fsS "http://127.0.0.1:$1" >/dev/null 2>&1; }

echo "==> Starting FastAPI backend (:8000)"
if curl -fsS "http://127.0.0.1:8000/api/health" >/dev/null 2>&1; then
  echo "Backend already running"
else
  nohup "$TENDER_REPO/.venv/bin/uvicorn" app.main:app \
    --app-dir "$TENDER_REPO/backend" --host 0.0.0.0 --port 8000 \
    >"$TENDER_RUNTIME/backend.log" 2>&1 &
  for _ in $(seq 1 40); do
    curl -fsS "http://127.0.0.1:8000/api/health" >/dev/null 2>&1 && break
    sleep 1
  done
fi

echo "==> Starting Vite frontend (:3000)"
if port_in_use 3000; then
  echo "Frontend already running"
else
  ( cd "$TENDER_REPO/frontend" && \
    nohup npm run dev -- --host 0.0.0.0 --port 3000 \
    >"$TENDER_RUNTIME/frontend.log" 2>&1 & )
  for _ in $(seq 1 30); do
    port_in_use 3000 && break
    sleep 1
  done
fi

echo "==> Stack ready:"
echo "    Frontend : http://localhost:3000"
echo "    Backend  : http://localhost:8000/docs"
echo "    MinIO    : http://localhost:9001 (minioadmin / minioadmin)"
