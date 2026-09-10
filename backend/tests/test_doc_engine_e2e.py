"""文档引擎黄金路径测试：Aspose 可用时跑端到端，否则跳过。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")


def _aspose_ready() -> bool:
    try:
        from app.services.aspose_runtime import ensure_license
        ensure_license()
        import aspose.words as aw  # noqa: F401
        from io import BytesIO
        doc = aw.Document()
        builder = aw.DocumentBuilder(doc)
        builder.writeln("golden")
        buf = BytesIO()
        doc.save(buf, aw.SaveFormat.DOCX)
        return len(buf.getvalue()) > 100
    except Exception:
        return False


def test_golden_engineer_render_pipeline():
    if not _aspose_ready():
        print("SKIP golden e2e: Aspose runtime unavailable")
        return
    from io import BytesIO
    import aspose.words as aw
    from app.services.doc_engine.engine import engineer_template_with_sdt, render_project_document
    from app.services.doc_engine.parser import parse_template_manifest
    import asyncio

    doc = aw.Document()
    builder = aw.DocumentBuilder(doc)
    builder.writeln("项目名称：{{project_name}}")
    builder.writeln("人员：{{staff_1_name}} / {{staff_1_role}}")
    builder.writeln("人员：{{staff_2_name}} / {{staff_2_role}}")
    tbl = builder.start_table()
    builder.insert_cell()
    builder.write("姓名")
    builder.insert_cell()
    builder.write("职务")
    builder.end_row()
    builder.insert_cell()
    builder.write("{{staff_name}}")
    builder.insert_cell()
    builder.write("{{staff_role}}")
    builder.end_table()
    buf = BytesIO()
    doc.save(buf, aw.SaveFormat.DOCX)
    tpl_bytes = buf.getvalue()

    manifest = parse_template_manifest(tpl_bytes)
    engineered, enriched = engineer_template_with_sdt(tpl_bytes, manifest)
    assert enriched.get("blocks")

    fields = {
        "project_name": "黄金路径测试项目",
        "staff_name": "张三",
        "staff_role": "项目经理",
        "staff_1_name": "李四",
        "staff_1_role": "技术员",
        "staff_2_name": "王五",
        "staff_2_role": "安全员",
        "staff_list": [
            {"staff_1_name": "李四", "staff_1_role": "技术员"},
            {"staff_1_name": "王五", "staff_1_role": "安全员"},
        ],
        "table_0_rows": [{"staff_name": "张三", "staff_role": "项目经理"}],
    }

    async def run():
        out, meta = await render_project_document(
            engineered,
            {"manifest_v2": enriched},
            fields,
            None,
            requirements="铁路维保项目投标",
            mode="create",
        )
        assert out and len(out) > 100
        assert meta.get("engine") == "doc_engine_v2"
        text_doc = aw.Document(BytesIO(out))
        text = text_doc.get_text() or ""
        assert "黄金路径测试项目" in text

    asyncio.run(run())
    print("PASS golden pipeline")


if __name__ == "__main__":
    test_golden_engineer_render_pipeline()
