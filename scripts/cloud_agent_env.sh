#!/usr/bin/env bash
# Shared environment for the Cloud Agent development setup of 标书智能体系统.
# Sourced by cloud_agent_install.sh, cloud_agent_start.sh and the dev runners.
#
# Everything is native (no Docker): PostgreSQL + MinIO run as local daemons,
# the FastAPI backend runs from a project virtualenv, and the React frontend
# runs via the Vite dev server that proxies /api to the backend.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export TENDER_REPO="$(cd "$SCRIPT_DIR/.." && pwd)"

# Persistent runtime state (Postgres cluster, MinIO data, downloaded binaries).
# Lives outside the git tree so the repo stays clean; captured by VM snapshots.
export TENDER_RUNTIME="${TENDER_RUNTIME:-$HOME/.tender}"
export PGDATA="$TENDER_RUNTIME/pgdata"
export MINIO_DATA="$TENDER_RUNTIME/miniodata"
export TENDER_BIN="$TENDER_RUNTIME/bin"

# PostgreSQL 16 (installed via apt).
export PG_BINDIR="/usr/lib/postgresql/16/bin"
export PGPORT="5432"

# Application configuration (mirrors docker-compose.yml defaults).
export DATABASE_URL="postgresql://tender:tender123@127.0.0.1:5432/tender_agent"
export MINIO_ENDPOINT="127.0.0.1:9000"
export MINIO_ACCESS_KEY="minioadmin"
export MINIO_SECRET_KEY="minioadmin"
export MINIO_BUCKET="tender-agent"
export MINIO_ROOT_USER="minioadmin"
export MINIO_ROOT_PASSWORD="minioadmin"

export SAMPLE_DATA_DIR="$TENDER_REPO/sample_data"
export CUSTOMER_DATA_DIR="$TENDER_REPO/customer_data/heyuanzhineng_20260729"
# Use the bundled sample_data seed (fully version-controlled). The customer pack
# requires an unpacked pack/ directory that is not committed.
export PREFER_CUSTOMER_PACK="false"
export CORS_ORIGINS="*"

# Aspose.Words license shipped in the repo (docs/...).
export ASPOSE_LICENSE_PATH="$TENDER_REPO/docs/Aspose.Words for Python  Developer OEM证书/Word究极工具/aspose-words/Aspose.License.txt"
# Linux x86_64 wheel bundles a .NET Core 3.1 runtime. That runtime cannot load
# ICU 74 (shipped on Ubuntu 24.04), so run .NET in globalization-invariant mode.
export DOTNET_SYSTEM_GLOBALIZATION_INVARIANT="1"

export PYTHONPATH="$TENDER_REPO/backend"
export PATH="$PG_BINDIR:$TENDER_BIN:$PATH"
