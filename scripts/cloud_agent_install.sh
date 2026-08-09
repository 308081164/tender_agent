#!/usr/bin/env bash
# Idempotent Cloud Agent install for 标书智能体系统 (native, no Docker).
#
# Prepares everything durable: system packages, Python virtualenv + backend deps
# (incl. the bundled Aspose.Words Linux wheel), frontend node_modules, a local
# PostgreSQL cluster with the tender role/database, and the MinIO server binary.
# Runtime daemons themselves are started by cloud_agent_start.sh on each boot.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/cloud_agent_env.sh
source "$SCRIPT_DIR/cloud_agent_env.sh"

ASPOSE_DIR="$TENDER_REPO/docs/Aspose.Words for Python  Developer OEM证书/Word究极工具/aspose-words"
ASPOSE_WHEEL="$ASPOSE_DIR/aspose_words-26.7.0-py3-none-manylinux1_x86_64.whl"

echo "==> [1/6] System packages"
export DEBIAN_FRONTEND=noninteractive
sudo apt-get update -y
sudo apt-get install -y --no-install-recommends \
  postgresql postgresql-contrib \
  libreoffice-writer libreoffice-java-common \
  fonts-wqy-zenhei fonts-wqy-microhei fonts-liberation fontconfig \
  curl ca-certificates python3-venv python3-pip
sudo fc-cache -f || true

# The Aspose .NET Core 3.1 runtime links against OpenSSL 1.1, which Ubuntu 24.04
# no longer ships. Install libssl1.1 (coexists with the system OpenSSL 3) so that
# DOCX->PDF conversion works. Skip if it is already present.
if ! ldconfig -p | grep -q 'libssl.so.1.1'; then
  echo "==> Installing libssl1.1 (required by Aspose's bundled .NET Core 3.1)"
  tmp_deb="$(mktemp --suffix=.deb)"
  curl -fsSL -o "$tmp_deb" \
    "http://archive.ubuntu.com/ubuntu/pool/main/o/openssl/libssl1.1_1.1.1f-1ubuntu2_amd64.deb"
  sudo dpkg -i "$tmp_deb" || sudo apt-get -f install -y
  rm -f "$tmp_deb"
fi

echo "==> [2/6] Python virtualenv + backend dependencies"
if [ ! -x "$TENDER_REPO/.venv/bin/python" ]; then
  python3 -m venv "$TENDER_REPO/.venv"
fi
"$TENDER_REPO/.venv/bin/pip" install --upgrade pip setuptools wheel
"$TENDER_REPO/.venv/bin/pip" install -r "$TENDER_REPO/backend/requirements.txt"
if ! "$TENDER_REPO/.venv/bin/python" -c "import aspose.words" >/dev/null 2>&1; then
  echo "==> Installing Aspose.Words wheel"
  "$TENDER_REPO/.venv/bin/pip" install "$ASPOSE_WHEEL"
fi

echo "==> [3/6] Frontend dependencies"
( cd "$TENDER_REPO/frontend" && (npm ci || npm install) )

echo "==> [4/6] MinIO server binary"
mkdir -p "$TENDER_BIN" "$MINIO_DATA"
if [ ! -x "$TENDER_BIN/minio" ]; then
  curl -fsSL -o "$TENDER_BIN/minio" https://dl.min.io/server/minio/release/linux-amd64/minio
  chmod +x "$TENDER_BIN/minio"
fi

echo "==> [5/6] PostgreSQL cluster + role/database"
mkdir -p "$TENDER_RUNTIME"
if [ ! -f "$PGDATA/PG_VERSION" ]; then
  "$PG_BINDIR/initdb" -D "$PGDATA" -U postgres --auth=trust --encoding=UTF8
fi
# Ensure the cluster is running (reuse it if already up) to create role/database.
STARTED_PG=0
if ! "$PG_BINDIR/pg_ctl" -D "$PGDATA" status >/dev/null 2>&1; then
  rm -f "$PGDATA/postmaster.pid" 2>/dev/null || true
  "$PG_BINDIR/pg_ctl" -D "$PGDATA" -l "$TENDER_RUNTIME/pg.log" \
    -o "-p $PGPORT -k /tmp" -w start
  STARTED_PG=1
fi
psql -h 127.0.0.1 -p "$PGPORT" -U postgres -tc \
  "SELECT 1 FROM pg_roles WHERE rolname='tender'" | grep -q 1 || \
  psql -h 127.0.0.1 -p "$PGPORT" -U postgres -c \
  "CREATE ROLE tender LOGIN PASSWORD 'tender123' SUPERUSER;"
psql -h 127.0.0.1 -p "$PGPORT" -U postgres -tc \
  "SELECT 1 FROM pg_database WHERE datname='tender_agent'" | grep -q 1 || \
  psql -h 127.0.0.1 -p "$PGPORT" -U postgres -c \
  "CREATE DATABASE tender_agent OWNER tender;"
# Only stop the cluster if this script started it (install leaves no daemons up).
if [ "$STARTED_PG" = "1" ]; then
  "$PG_BINDIR/pg_ctl" -D "$PGDATA" -w stop || true
fi

echo "==> [6/6] Smoke-test Aspose.Words runtime"
"$TENDER_REPO/.venv/bin/python" - <<'PY'
import aspose.words as aw
d = aw.Document(); b = aw.DocumentBuilder(d); b.writeln("install smoke test")
print("Aspose.Words OK")
PY

echo "==> Install complete."
