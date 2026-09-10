"""文档引擎 v2 单元测试（不依赖 Aspose 的部分）。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from app.services.doc_engine.composition import _parse_json_array
from app.services.doc_engine.manifest import (
    empty_manifest,
    get_manifest,
    infer_mode,
    set_manifest,
)
from app.services.doc_engine.replacement import build_image_bindings_from_quals


def test_manifest_roundtrip():
    m = empty_manifest("create")
    m["blocks"] = [{"id": "field.project_name", "type": "field_slot", "bind": "project_name"}]
    ph = set_manifest({"list": ["project_name"]}, m)
    loaded = get_manifest(ph)
    assert loaded is not None
    assert loaded["mode"] == "create"
    assert len(loaded["blocks"]) == 1


def test_infer_mode():
    blocks = [{"type": "ai_section"}, {"type": "field_slot"}, {"type": "field_slot"}]
    assert infer_mode(blocks, 5, False) in ("hybrid", "create")
    assert infer_mode([], 0, True) == "replace"


def test_parse_json_array():
    raw = '[{"block_id":"ai.x","outline":["a"]}]'
    arr = _parse_json_array(raw)
    assert arr and arr[0]["block_id"] == "ai.x"


def test_image_bindings():
    manifest = {
        "blocks": [
            {"type": "image_slot", "anchor": {"location": "img:0"}, "bind": {"qual_name": "营业执照"}},
        ],
    }
    quals = [{
        "name": "营业执照",
        "category": "企业资质包",
        "file_type": "jpg",
        "data": b"fake",
    }]
    binds = build_image_bindings_from_quals(manifest, quals, None)
    assert len(binds) == 1
    assert binds[0]["location"] == "img:0"


if __name__ == "__main__":
    test_manifest_roundtrip()
    test_infer_mode()
    test_parse_json_array()
    test_image_bindings()
    print("ok")
