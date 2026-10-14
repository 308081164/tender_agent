"""测试收集前准备：没有商业 Aspose 包时用替身，避免导入即失败。"""
from __future__ import annotations

import sys


def _ensure_aspose_stub() -> None:
    try:
        import aspose.words  # noqa: F401
    except Exception:
        from unittest.mock import MagicMock

        sys.modules.setdefault("aspose", MagicMock())
        sys.modules.setdefault("aspose.words", MagicMock())


_ensure_aspose_stub()
