"""文档引擎 v2 深化功能单元测试（纯逻辑，不依赖 Aspose 运行时）。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from app.services.doc_engine.bundles import infer_qual_bundles, infer_repeat_blocks
from app.services.doc_engine.image_bindings import suggest_image_slot_bindings, update_manifest_block_bind
from app.services.doc_engine.ocr_match import rank_quals_for_slot, score_qual_match
from app.services.ocr_service import extract_text_from_file
from app.services.doc_engine.qual_insert import match_heading_for_qual
from app.services.doc_engine.sdt import normalize_tag, tag_to_block_id
from app.services.doc_engine.tables import infer_table_slots, parse_rows_data, resolve_table_rows


def test_sdt_tag_helpers():
    assert normalize_tag("field.project_name") == "tender.field.project_name"
    assert tag_to_block_id("tender.ai.tech") == "ai.tech"


def test_infer_table_slots():
    index = {
        "tables": [{
            "index": 0,
            "rows": [
                [{"text": "姓名", "placeholders": [], "location": "tbl:0:r0:c0"}],
                [{"text": "{{staff_name}}", "placeholders": ["staff_name"], "location": "tbl:0:r1:c0"}],
            ],
        }],
    }
    blocks = infer_table_slots(index)
    assert len(blocks) == 1
    assert blocks[0]["type"] == "table_slot"
    assert blocks[0]["columns"] == ["staff_name"]


def test_parse_rows_data():
    rows = parse_rows_data('[{"staff_name":"张三"},{"staff_name":"李四"}]')
    assert len(rows) == 2
    assert rows[0]["staff_name"] == "张三"


def test_resolve_table_rows():
    block = {"bind": "staff_rows", "columns": ["staff_name", "role"]}
    fields = {"staff_rows": [{"staff_name": "王五", "role": "项目经理"}]}
    rows = resolve_table_rows(block, fields)
    assert rows[0]["role"] == "项目经理"


def test_ocr_match_prefers_name():
    quals = [
        {"name": "营业执照", "category": "企业资质", "ocr_text": "营业执照 统一社会信用代码"},
        {"name": "安全生产许可证", "category": "企业资质", "ocr_text": "安许证"},
    ]
    ranked = rank_quals_for_slot(quals, {"qual_name": "营业执照"})
    assert ranked[0]["name"] == "营业执照"
    score = score_qual_match(quals[0], qual_name="营业执照", context="企业资质包")
    assert score >= 0.4


def test_infer_qual_bundles_and_repeat():
    index = {
        "paragraphs": [
            {"text": "二、企业资质", "is_heading": True, "location": "p:1"},
            {"text": "人员：{{staff_1_name}}", "location": "p:2", "placeholders": ["staff_1_name"]},
            {"text": "人员：{{staff_2_name}}", "location": "p:3", "placeholders": ["staff_2_name"]},
        ],
        "images": [{"location": "img:0", "alt": "营业执照"}],
    }
    bundles = infer_qual_bundles(index)
    assert any(b["type"] == "qual_bundle" for b in bundles)
    repeats = infer_repeat_blocks(index)
    assert any(b["type"] == "repeat_block" for b in repeats)


def test_image_binding_update():
    manifest = {
        "blocks": [{"id": "image.0", "type": "image_slot", "bind": {}, "anchor": {"location": "img:0"}}],
    }
    updated = update_manifest_block_bind(manifest, "image.0", {"qual_name": "营业执照"})
    block = updated["blocks"][0]
    assert block["bind"]["qual_name"] == "营业执照"
    suggestions = suggest_image_slot_bindings(manifest, {"images": [{"alt": "执照"}], "paragraphs": []})
    assert suggestions


def test_ocr_fallback_metadata():
    text = extract_text_from_file(b"", "jpg", name="营业执照", keywords="统一社会信用代码", category="企业资质")
    assert "营业执照" in text


def test_match_heading_for_qual():
    headings = [
        {"text": "一、投标函"},
        {"text": "二、企业资质"},
        {"text": "三、技术方案"},
    ]
    qual = {"name": "营业执照", "category": "企业资质", "section_hint": "企业资质", "ocr_text": ""}
    idx = match_heading_for_qual(qual, headings)
    assert idx == 1


if __name__ == "__main__":
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        fn()
        print(f"PASS {fn.__name__}")
