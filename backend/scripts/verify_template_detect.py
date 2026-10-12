#!/usr/bin/env python3
"""本地验证模板工程化 Step1「智能识别」依赖的 DOCX 预览与索引（无需 LLM）。"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
sys.path.insert(0, str(ROOT))

DEFAULT_DOC = (
    REPO
    / "docs"
    / "标书智能体参考资料-和远智能-20260729"
    / "02-word标书模板"
    / "1-标准投标word模板"
    / "铁路工程投标模板2-空白.docx"
)
DEFAULT_LICENSE = (
    REPO
    / "docs"
    / "Aspose.Words for Python  Developer OEM证书"
    / "Word究极工具"
    / "aspose-words"
    / "Aspose.License.txt"
)


def main() -> int:
    doc_path = Path(os.environ.get("VERIFY_TEMPLATE_DOCX", str(DEFAULT_DOC)))
    if not doc_path.is_file():
        print(f"ERROR: 模板不存在: {doc_path}", file=sys.stderr)
        return 1
    lic = os.environ.get("ASPOSE_LICENSE_PATH", str(DEFAULT_LICENSE))
    os.environ["ASPOSE_LICENSE_PATH"] = lic

    from app.services.aspose_runtime import ensure_license, license_path
    from app.services import word, template_detect
    from app.services.doc_engine.indexer import build_document_index

    license_path.cache_clear()
    ensure_license()
    data = doc_path.read_bytes()

    preview = word.extract_preview(data, max_paragraphs=120)
    paras = preview.get("paragraphs") or []
    if not paras:
        print("ERROR: extract_preview 未返回段落", file=sys.stderr)
        return 1

    index = build_document_index(data)
    if not (index.get("paragraphs") or index.get("tables")):
        print("ERROR: build_document_index 为空", file=sys.stderr)
        return 1

    async def _detect():
        with patch("app.services.ai.detect_placeholder_candidates", new=AsyncMock(return_value=[])), patch(
            "app.services.ai.resolve_placeholder_mappings",
            new=AsyncMock(side_effect=lambda c, *a, **k: c),
        ):
            return await template_detect.detect_placeholder_candidates(
                data,
                [{"key": "project_name", "name": "项目名称", "field_type": "文本", "module": "基础"}],
                db=None,
            )

    result = asyncio.run(_detect())
    stats = result.get("mapping_stats") or {}
    print(
        f"OK doc={doc_path.name} paragraphs={len(paras)} "
        f"index_paras={len(index.get('paragraphs') or [])} "
        f"candidates={stats.get('total', len(result.get('candidates') or []))}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
