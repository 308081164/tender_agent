#!/bin/sh
set -e

install_aspose_if_needed() {
  if python -c "import aspose.words" >/dev/null 2>&1; then
    return 0
  fi
  if [ ! -d /aspose ]; then
    echo "[entrypoint] /aspose 未挂载，无法安装 Aspose.Words"
    return 1
  fi

  arch="$(uname -m)"
  wheel=""
  case "$arch" in
    x86_64)
      wheel="$(ls /aspose/aspose_words-*-manylinux1_x86_64.whl 2>/dev/null | head -1)"
      ;;
    aarch64|arm64)
      wheel="$(ls /aspose/aspose_words-*-manylinux*aarch64*.whl 2>/dev/null | head -1)"
      ;;
    *)
      wheel=""
      ;;
  esac

  if [ -z "$wheel" ]; then
    echo "[entrypoint] 当前架构 ${arch} 未找到匹配的 Aspose whl"
    return 1
  fi

  echo "[entrypoint] 安装 Aspose: $(basename "$wheel")"
  pip install --no-cache-dir "$wheel"
}

install_aspose_if_needed
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
