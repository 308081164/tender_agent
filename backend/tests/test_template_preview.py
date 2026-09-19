"""模板映射预览：域代码过滤、空白待填识别、表格预览逻辑。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from app.services.template_detect import _blank_fill_candidates, _is_junk_text
from app.services.word import is_field_code_text, simulate_mapping_preview


def test_is_field_code_text_filters_toc_hyperlink():
    assert is_field_code_text('TOC \\o "1-3" \\h \\u')
    assert is_field_code_text('PAGE \\* MERGEFORMAT')
    assert is_field_code_text('HYPERLINK \\l "_Toc5562"')
    assert not is_field_code_text('谈判响应文件')
    assert not is_field_code_text('目录')


def test_is_junk_text_delegates_to_field_code():
    assert _is_junk_text('PAGEREF _Toc5562 \\h 1')
    assert not _is_junk_text('2025年7月1日')


def test_blank_fill_candidates_signature_and_date():
    catalog = [{"key": "sign_date", "name": "签署日期"}]
    paras = [
        {"text": "法定代表人： （签字）", "location": "p:0"},
        {"text": "年  月  日", "location": "p:1"},
        {"text": "委托期限：____", "location": "p:2"},
    ]
    found = _blank_fill_candidates(paras, catalog)
    texts = {x["original_text"] for x in found}
    assert "（签字）" in texts
    assert any("年" in t and "月" in t for t in texts)
    assert any("委托期限" in t for t in texts)


def test_blank_fill_form_label_pair():
    catalog = []
    paras = [
        {"text": "竞标人名称", "location": "p:0"},
        {"text": "", "location": "p:1"},
        {"text": "注册地址", "location": "p:2"},
        {"text": "上海市浦东新区", "location": "p:3"},
    ]
    found = _blank_fill_candidates(paras, catalog)
    assert any("竞标人名称" in x["original_text"] for x in found)
    assert not any(x["original_text"] == "注册地址" for x in found)


def test_simulate_mapping_preview_table_cells():
    paragraphs = [{
        "text": "",
        "is_table": True,
        "table_rows": [["姓名", "职务"], ["张三", "项目经理"]],
    }]
    mappings = [{
        "approved": True,
        "action": "replace",
        "original_text": "张三",
        "key": "contact_name",
        "bind_type": "field",
    }]
    result = simulate_mapping_preview(paragraphs, mappings)
    assert result[0]["display_table_rows"][1][0] == "{{contact_name}}"
    assert result[0]["changed"] is True
