"""模板映射预览：域代码过滤、空白待填识别、表格预览逻辑。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from app.services.aspose_runtime import iter_collection
from app.services.template_detect import _blank_fill_candidates, _is_junk_text
from app.services.word import is_field_code_text, simulate_mapping_preview


def test_is_field_code_text_filters_toc_hyperlink():
    assert is_field_code_text('TOC \\o "1-3" \\h \\u')
    assert is_field_code_text('PAGE \\* MERGEFORMAT')
    assert is_field_code_text('HYPERLINK \\l "_Toc5562"')
    assert not is_field_code_text('谈判响应文件')
    assert not is_field_code_text('目录')


def test_toc_style_and_entry_detection():
    from app.services.word import (
        is_heading_style_name,
        is_toc_entry_text,
        is_toc_style_name,
        paragraph_is_toc_like,
    )

    assert is_toc_style_name("toc 1")
    assert is_toc_style_name("TOC 2")
    assert not is_heading_style_name("toc 1")
    assert is_heading_style_name("Heading 1")
    assert is_toc_entry_text("2. 法定代表人身份证明\t2")
    assert paragraph_is_toc_like("toc 1", "4. 资格证明资料\t4")
    assert not paragraph_is_toc_like("Heading 1", "竞标函")


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


def test_iter_collection_uses_index_not_python_for_in():
    """Aspose Section/Row 集合 for-in 产出无 .body/.cells 的 Node，必须按下标迭代。"""

    class FakeCells:
        def __init__(self, cells):
            self._cells = cells

        @property
        def count(self):
            return len(self._cells)

        def __getitem__(self, i):
            return self._cells[i]

        def __iter__(self):
            yield BrokenNode()

    class FakeRow:
        def __init__(self, texts):
            self._cells = FakeCells([FakeCell(t) for t in texts])

        @property
        def cells(self):
            return self._cells

    class FakeCell:
        def __init__(self, text):
            self._text = text

        def get_text(self):
            return self._text

    class FakeSection:
        @property
        def body(self):
            return "body"

    class FakeSections:
        def __init__(self):
            self._items = [FakeSection()]

        @property
        def count(self):
            return len(self._items)

        def __getitem__(self, i):
            return self._items[i]

        def __iter__(self):
            yield BrokenNode()

    class BrokenNode:
        pass

    sections = list(iter_collection(FakeSections()))
    assert sections[0].body == "body"
    row = FakeRow(["a", "b"])
    cells = [c.get_text() for c in iter_collection(row.cells)]
    assert cells == ["a", "b"]


def test_extract_preview_railway_blank_docx():
    """集成：铁路工程空白模板应能 extract_preview（回归 #404509e for-in 迭代）。"""
    from pathlib import Path

    from app.services import word

    candidates = [
        Path("/workspace/docs/标书智能体参考资料-和远智能-20260729/02-word标书模板/1-标准投标word模板/铁路工程投标模板2-空白.docx"),
        Path("/workspace/sample_data/02_Word标书模板/标准投标Word模板/铁路工程投标模板1-工程化.docx"),
    ]
    doc_path = next((p for p in candidates if p.is_file()), None)
    if not doc_path:
        return
    lic = os.environ.get("ASPOSE_LICENSE_PATH", "").strip()
    if not lic or not Path(lic).is_file():
        return
    try:
        from app.services.aspose_runtime import ensure_license

        ensure_license()
    except Exception:
        return
    data = doc_path.read_bytes()
    preview = word.extract_preview(data, max_paragraphs=80)
    assert preview.get("paragraphs")
    assert any(p.get("text") or p.get("is_table") for p in preview["paragraphs"])


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
