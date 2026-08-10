#!/usr/bin/env bash
# 桌面端后端启动验证（Linux/CI 可用）
# 使用 Docker 启动 PostgreSQL + MinIO，模拟 TENDER_DESKTOP 环境并检查 /api/health 与前端静态资源。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

VERIFY_DATA="$ROOT/.desktop-verify-data"
VENV="$ROOT/.desktop-verify-venv"
ASPOSE_DIR="$ROOT/docs/Aspose.Words for Python  Developer OEM证书/Word究极工具/aspose-words"
ASPOSE_WHEEL="$(find "$ASPOSE_DIR" -name 'aspose_words-*-manylinux1_x86_64.whl' | head -1)"
PORT=18766
HEALTH_URL="http://127.0.0.1:${PORT}/api/health"
ROOT_URL="http://127.0.0.1:${PORT}/"

compose() {
  if docker compose version >/dev/null 2>&1; then
    docker compose "$@"
  elif command -v docker-compose >/dev/null 2>&1; then
    docker-compose "$@"
  else
    echo "ERROR: docker compose not available" >&2
    exit 1
  fi
}

install_aspose_deps() {
  bash "$ROOT/scripts/ci/install-aspose-linux-deps.sh"
}

preflight_aspose() {
  local license_path="$1"
  echo "==> Aspose 运行时自检"
  DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1 \
    "$VENV/bin/python" -c "
import os
os.environ.setdefault('DOTNET_SYSTEM_GLOBALIZATION_INVARIANT', '1')
from aspose.words import License
License().set_license(os.environ['ASPOSE_LICENSE_PATH'])
print('Aspose license OK')
" ASPOSE_LICENSE_PATH="$license_path"
}

wait_for_db() {
  local max_attempts="${1:-90}"
  local attempt
  for attempt in $(seq 1 "$max_attempts"); do
    if compose exec -T db pg_isready -U tender -d tender_agent >/dev/null 2>&1; then
      echo "postgres ready (attempt ${attempt})"
      return 0
    fi
    if compose exec -T db pg_isready -U tender >/dev/null 2>&1; then
      echo "postgres accepting connections (attempt ${attempt})"
      return 0
    fi
    if (( attempt % 10 == 0 )); then
      echo "  still waiting for postgres... (${attempt}/${max_attempts})"
      compose ps db minio || true
    fi
    sleep 2
  done
  echo "ERROR: postgres did not become ready in time" >&2
  compose ps db minio || true
  compose logs db --tail 40 || true
  return 1
}

wait_for_minio() {
  local max_attempts="${1:-60}"
  local attempt
  for attempt in $(seq 1 "$max_attempts"); do
    if curl -fsS "http://127.0.0.1:9000/minio/health/live" >/dev/null 2>&1; then
      echo "minio ready (attempt ${attempt})"
      return 0
    fi
    sleep 2
  done
  echo "ERROR: minio did not become ready in time" >&2
  compose logs minio --tail 40 || true
  return 1
}

cleanup() {
  if [[ -n "${UVICORN_PID:-}" ]] && kill -0 "$UVICORN_PID" 2>/dev/null; then
    kill "$UVICORN_PID" 2>/dev/null || true
    wait "$UVICORN_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

echo "==> [1/6] 启动基础设施 (PostgreSQL + MinIO)"
if compose up -d --wait db minio 2>/dev/null; then
  echo "docker compose --wait: services healthy"
else
  compose up -d db minio
fi

echo "==> [2/6] 等待数据库就绪"
wait_for_db 90
wait_for_minio 60

echo "==> [3/6] 构建前端"
if [[ ! -d "$ROOT/frontend/node_modules" ]]; then
  (cd "$ROOT/frontend" && npm install --silent)
fi
(cd "$ROOT/frontend" && npm run build)

echo "==> [4/6] 准备 Python 运行时"
install_aspose_deps
if [[ ! -x "$VENV/bin/python" ]]; then
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install -q -U pip
  "$VENV/bin/pip" install -q -r "$ROOT/backend/requirements.txt"
  if [[ -z "$ASPOSE_WHEEL" || ! -f "$ASPOSE_WHEEL" ]]; then
    echo "ERROR: 未找到 Linux Aspose wheel" >&2
    exit 1
  fi
  "$VENV/bin/pip" install -q "$ASPOSE_WHEEL"
fi

export DOTNET_SYSTEM_GLOBALIZATION_INVARIANT="${DOTNET_SYSTEM_GLOBALIZATION_INVARIANT:-1}"

rm -rf "$VERIFY_DATA"
mkdir -p "$VERIFY_DATA"

export TENDER_DESKTOP=1
export TENDER_INSTALL_DIR="$ROOT"
export TENDER_DATA_DIR="$VERIFY_DATA"
export ASPOSE_LICENSE_PATH="$ASPOSE_DIR/Aspose.License.txt"
if [[ ! -f "$ASPOSE_LICENSE_PATH" ]]; then
  echo "ERROR: Aspose license not found: $ASPOSE_LICENSE_PATH" >&2
  exit 1
fi
preflight_aspose "$ASPOSE_LICENSE_PATH"
export DATABASE_URL="postgresql://tender:tender123@127.0.0.1:5432/tender_agent"
export MINIO_ENDPOINT="127.0.0.1:9000"
export MINIO_ACCESS_KEY="minioadmin"
export MINIO_SECRET_KEY="minioadmin"
export MINIO_BUCKET="tender-agent"
export SAMPLE_DATA_DIR="$ROOT/sample_data"
export CUSTOMER_DATA_DIR="$ROOT/customer_data/heyuanzhineng_20260729"
export PYTHONPATH="$ROOT/backend"

echo "==> [5/6] 启动 uvicorn (桌面模式)"
"$VENV/bin/uvicorn" app.main:app \
  --app-dir "$ROOT/backend" \
  --host 127.0.0.1 \
  --port "$PORT" \
  >"$VERIFY_DATA/backend.log" 2>&1 &
UVICORN_PID=$!

echo "==> [6/6] 健康检查"
for _ in $(seq 1 60); do
  if curl -fsS "$HEALTH_URL" >/dev/null 2>&1; then
    break
  fi
  if ! kill -0 "$UVICORN_PID" 2>/dev/null; then
    echo "ERROR: uvicorn 已退出，日志：" >&2
    tail -n 40 "$VERIFY_DATA/backend.log" >&2 || true
    exit 1
  fi
  sleep 1
done

curl -fsS "$HEALTH_URL" | tee "$VERIFY_DATA/health.json"
curl -fsS "$ROOT_URL" | head -c 200 | tee "$VERIFY_DATA/root.html" >/dev/null
echo ""
echo "VERIFY_OK: desktop backend healthy on port $PORT"
echo "Logs: $VERIFY_DATA/backend.log"
