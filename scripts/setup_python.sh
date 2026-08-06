#!/usr/bin/env bash
# 初始化本地 Python 3.11 虚拟环境（勿使用 Xcode 自带 Python 3.9，会导致 Aspose 崩溃）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PY311="/opt/homebrew/opt/python@3.11/bin/python3.11"
ASPOSE_DIR="$ROOT/docs/Aspose.Words for Python  Developer OEM证书/Word究极工具/aspose-words"
WHEEL="$ASPOSE_DIR/aspose_words-26.7.0-py3-none-macosx_11_0_arm64.whl"

if [[ ! -x "$PY311" ]]; then
  echo "未找到 Homebrew Python 3.11，请先执行: brew install python@3.11"
  exit 1
fi
if [[ ! -f "$WHEEL" ]]; then
  echo "未找到 Aspose whl: $WHEEL"
  exit 1
fi

"$PY311" -m venv .venv
.venv/bin/pip install -U pip setuptools wheel
.venv/bin/pip install -r backend/requirements.txt
.venv/bin/pip install --force-reinstall "$WHEEL"

echo
echo "本地环境就绪。请使用:"
echo "  source .venv/bin/activate"
echo "  export ASPOSE_LICENSE_PATH=\"$ASPOSE_DIR/Aspose.License.txt\""
echo "  python backend/scripts/test_aspose.py"
