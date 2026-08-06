#!/usr/bin/env bash
# Apple Silicon 本地开发：Docker 跑 db/minio/frontend，后端在宿主机用 Aspose macOS arm64。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PY="${ROOT}/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  echo "未找到 .venv，正在用 Homebrew Python 3.11 创建..."
  /opt/homebrew/opt/python@3.11/bin/python3.11 -m venv .venv
  .venv/bin/pip install -U pip
  .venv/bin/pip install -r backend/requirements.txt
  .venv/bin/pip install --force-reinstall \
    "docs/Aspose.Words for Python  Developer OEM证书/Word究极工具/aspose-words/aspose_words-26.7.0-py3-none-macosx_11_0_arm64.whl"
fi

export BACKEND_UPSTREAM="host.docker.internal:8000"
docker compose stop backend 2>/dev/null || true
docker compose up -d --build db minio frontend

export DATABASE_URL="postgresql://tender:tender123@127.0.0.1:5432/tender_agent"
export MINIO_ENDPOINT="127.0.0.1:9000"
export MINIO_ACCESS_KEY="minioadmin"
export MINIO_SECRET_KEY="minioadmin"
export MINIO_BUCKET="tender-agent"
export SAMPLE_DATA_DIR="${ROOT}/sample_data"
export CUSTOMER_DATA_DIR="${ROOT}/customer_data/heyuanzhineng_20260729"
export PREFER_CUSTOMER_PACK="true"
export CORS_ORIGINS="*"
export ASPOSE_LICENSE_PATH="${ROOT}/docs/Aspose.Words for Python  Developer OEM证书/Word究极工具/aspose-words/Aspose.License.txt"
export PYTHONPATH="${ROOT}/backend"

echo "等待数据库就绪..."
for i in $(seq 1 30); do
  if docker compose exec -T db pg_isready -U tender -d tender_agent >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

echo "启动本机后端 (Aspose macOS arm64) → http://127.0.0.1:8000"
echo "前端 → http://127.0.0.1:3000"
exec "${ROOT}/.venv/bin/uvicorn" app.main:app --app-dir backend --host 0.0.0.0 --port 8000 --reload
