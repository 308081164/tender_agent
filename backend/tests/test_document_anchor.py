"""document_anchor 单元测试。"""
from __future__ import annotations

from app.services.agent_capabilities import anchor_can_insert, resolve_document_anchor
from app.services.document_anchor import (
    anchor_has_table_cell,
    finalize_document_anchor,
    normalize_table_location,
)


def test_resolve_table_location_from_context():
    anchor = resolve_document_anchor({
        "location": "tbl:2:r1:c3",
        "selected_text": "待填写",
    })
    assert anchor["ok"]
    assert anchor["location"] == "tbl:2:r1:c3"
    assert anchor["table_index"] == 2
    assert anchor["row"] == 1
    assert anchor["col"] == 3
    assert anchor_has_table_cell(anchor)
    assert anchor_can_insert(anchor)


def test_normalize_table_location_from_parts():
    raw = {"ok": True, "table_index": 1, "row": 0, "col": 2}
    out = normalize_table_location(raw)
    assert out["location"] == "tbl:1:r0:c2"
    assert out.get("in_table_cell")


def test_finalize_without_doc_passes_through():
    anchor = resolve_document_anchor({"selected_text": "x", "paragraph_index": 5})
    out = finalize_document_anchor(anchor, None)
    assert out.get("paragraph_index") == 5
