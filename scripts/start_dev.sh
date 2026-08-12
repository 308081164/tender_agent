#!/usr/bin/env bash
# 本地开发启动：Docker 跑 db/minio/frontend，本机 .venv 跑 backend（Aspose 需在 macOS arm64 运行）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

ASPOSE_DIR="$ROOT/docs/Aspose.Words for Python  Developer OEM证书/Word究极工具/aspose-words"
export ASPOSE_LICENSE_PATH="$ASPOSE_DIR/Aspose.License.txt"
export DATABASE_URL="${DATABASE_URL:-postgresql://tender:tender123@127.0.0.1:5432/tender_agent}"
export MINIO_ENDPOINT="${MINIO_ENDPOINT:-127.0.0.1:9000}"
export MINIO_ACCESS_KEY="${MINIO_ACCESS_KEY:-minioadmin}"
export MINIO_SECRET_KEY="${MINIO_SECRET_KEY:-minioadmin}"
export MINIO_BUCKET="${MINIO_BUCKET:-tender-agent}"
export SAMPLE_DATA_DIR="${SAMPLE_DATA_DIR:-$ROOT/sample_data}"
export CORS_ORIGINS="${CORS_ORIGINS:-*}"
export ONLYOFFICE_ENABLED="${ONLYOFFICE_ENABLED:-true}"
export ONLYOFFICE_DOCUMENT_SERVER_URL="${ONLYOFFICE_DOCUMENT_SERVER_URL:-http://localhost:8080}"
export ONLYOFFICE_JWT_SECRET="${ONLYOFFICE_JWT_SECRET:-onlyoffice-jwt-secret-change-me}"
export ONLYOFFICE_INTERNAL_URL="${ONLYOFFICE_INTERNAL_URL:-http://host.docker.internal:8000}"

if [ ! -x "$ROOT/.venv/bin/python" ]; then
  echo "未找到 .venv，请先运行: bash scripts/setup_python.sh"
  exit 1
fi

echo "启动基础设施 (db / minio / onlyoffice / frontend)..."
docker compose up -d db minio onlyoffice frontend

echo "停止 Docker 内 backend（改用本机 Python 3.11）..."
docker compose stop backend 2>/dev/null || true

echo "启动本机 backend :8000 ..."
exec "$ROOT/.venv/bin/uvicorn" app.main:app --app-dir "$ROOT/backend" --host 0.0.0.0 --port 8000 --reload
