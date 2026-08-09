#!/usr/bin/env bash
# Per-boot startup for the Cloud Agent dev environment: bring up PostgreSQL and
# MinIO, then return. Idempotent and safe to run repeatedly. The backend and
# frontend dev servers are launched separately (see the "terminals" entries in
# the environment configuration / scripts/backend_dev.sh + frontend_dev.sh).
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
