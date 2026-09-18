"""映射资源目录搜索测试。"""
import json
import re

from app.services.mapping_resources import search_mapping_resources


def test_search_mapping_resources_keyword():
    catalog = {
        "all_bindable": [
            {"key": "tender_no", "name": "招标编号", "search_text": "招标编号 tender_no", "bind_type": "field"},
            {"key": "bid_date", "name": "投标日期", "search_text": "投标日期 bid_date 日期", "bind_type": "field"},
            {"key": "qual_1", "name": "营业执照", "search_text": "营业执照 资质", "bind_type": "qual", "id": 1},
        ]
    }
    hits = search_mapping_resources(catalog, "日期")
    assert any(x["key"] == "bid_date" for x in hits)
    assert not any(x["key"] == "tender_no" for x in hits)


def test_parse_resolve_json_shape():
    """验证 AI 映射决策 JSON 结构可被解析（不依赖 template_detect 模块）。"""
    raw = """[
      {"key": "qual_3", "field_name": "营业执照", "original_text": "营业执照副本", "bind_type": "qual", "qualification_id": 3},
      {"key": "package_desc", "field_name": "包件说明", "original_text": "包件一", "bind_type": "runtime",
       "suggested_field": {"key": "package_desc", "name": "包件说明", "field_type": "文本"}}
    ]"""
    data = json.loads(raw)
    assert data[0]["qualification_id"] == 3
    assert data[1]["suggested_field"]["key"] == "package_desc"


def test_junk_word_field_code_pattern():
    junk = re.compile(r"PAGE\s*\\", re.I)
    assert junk.search("PAGE \\* MERGEFORMAT 1")
    assert not junk.search("沪宁段四电工程HSQD标")
