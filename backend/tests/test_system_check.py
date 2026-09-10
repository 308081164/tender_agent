"""环境自检 API 逻辑测试。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from app.services.ocr_service import ocr_runtime_status, resolve_tesseract_cmd
from app.services.system_check import run_system_check


def test_ocr_runtime_status():
    st = ocr_runtime_status()
    assert "tesseract_available" in st


def test_system_check_structure():
    result = run_system_check(None)
    assert result["status"] in ("green", "yellow", "red")
    assert isinstance(result.get("checks"), list)
    ids = {c["id"] for c in result["checks"]}
    assert "doc_engine" in ids
    assert "ocr" in ids


if __name__ == "__main__":
    test_ocr_runtime_status()
    test_system_check_structure()
    print("ok")
