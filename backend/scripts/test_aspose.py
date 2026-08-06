#!/usr/bin/env python3
"""Aspose.Words 授权与导出冒烟测试。"""
from __future__ import annotations

import os
import sys
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
sys.path.insert(0, str(ROOT))

os.environ["ASPOSE_LICENSE_PATH"] = str(
    REPO
    / "docs"
    / "Aspose.Words for Python  Developer OEM证书"
    / "Word究极工具"
    / "aspose-words"
    / "Aspose.License.txt"
)

from app.services import aspose_runtime, word  # noqa: E402
from app.services.aspose_runtime import license_path  # noqa: E402

license_path.cache_clear()


def main() -> int:
    print("[1/3] 加载授权...")
    aspose_runtime.ensure_license()
    print(f"      license: {aspose_runtime.license_path()}")

    print("[2/3] 生成空白文档...")
    info = aspose_runtime.smoke_test()
    print(f"      {info}")

    print("[3/3] 占位符替换...")
    import aspose.words as aw

    doc = aw.Document()
    builder = aw.DocumentBuilder(doc)
    builder.writeln("项目名称：{{project_name}}")
    builder.writeln("招标编号：{{tender_no}}")
    stream = BytesIO()
    doc.save(stream, aw.SaveFormat.DOCX)
    template = stream.getvalue()

    fields = {"project_name": "测试项目", "tender_no": "ZB-2026-001"}
    rendered = word.render_document(template, fields, highlight=True)
    text = "\n".join(p["text"] for p in word.extract_preview(rendered)["paragraphs"])
    assert "测试项目" in text and "ZB-2026-001" in text
    assert "{{project_name}}" not in text
    print(f"      placeholders: {word.extract_placeholders(template)}")
    print("Aspose 集成测试通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
