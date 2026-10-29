"""Document Map 与 Agent 文档工具单元测试。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.docx_ooxml import build_styled_docx, insert_table
from app.services.doc_engine.compose_policy import section_has_letter_skeleton
from app.services.doc_engine.document_map import (
    build_document_map,
    compact_outline_for_agent,
    read_section_payload,
    region_allows_ai_narrative_write,
)


def _heading_doc(title: str, table_cells: list[list[str]] | None = None) -> bytes:
    doc = build_styled_docx([(title, "Heading1")])
    if table_cells:
        doc = insert_table(doc, 0, rows=len(table_cells), cols=len(table_cells[0]), cells=table_cells)
    return doc


def test_build_document_map_detects_heading_and_table():
    doc = _heading_doc("一、基本情况表", [["序号", "名称"], ["1", ""]])
    doc_map = build_document_map(doc, {"blocks": []})
    assert doc_map["table_count"] >= 1
    assert doc_map["empty_slot_count"] >= 1
    compact = compact_outline_for_agent(doc_map)
    assert compact["empty_slots"]


def test_region_blocks_ai_on_form_table_section():
    doc = _heading_doc("认证证书表", [["认证名称", "编号"], ["", ""]])
    allowed = region_allows_ai_narrative_write(doc, "认证证书表")
    assert allowed is False


def test_read_section_payload():
    doc = build_styled_docx([
        ("技术方案", "Heading1"),
        ("第一段说明。", None),
        ("第二段说明。", None),
    ])
    payload = read_section_payload(doc, "技术方案")
    assert payload.get("ok") is True
    assert "第一段" in payload.get("text", "")


def test_section_has_letter_skeleton():
    doc = build_styled_docx([
        ("竞标函", "Heading1"),
        ("致：采购人", None),
        (
            "我方参加本次招标项目投标，将严格按招标文件要求编制并提交全部投标文件。"
            "我方承诺响应全部实质性条款并承担相应法律责任。特此说明。",
            None,
        ),
        ("法定代表人（盖单位章）", None),
        ("年月日", None),
    ])
    assert section_has_letter_skeleton(doc, "竞标函") is True
