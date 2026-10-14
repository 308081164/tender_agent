"""联网搜索：意图、引用与离线失败。"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

for _name in ("aspose", "aspose.words"):
    sys.modules.setdefault(_name, MagicMock())

import httpx

from app.services.agent_semantic import _keyword_route
from app.services.agent_tool_loop import TOOL_SPECS, _execute_tool
from app.services.chat_assistant import _score_intent, process_chat_message
from app.services.web_search import (
    extract_search_query,
    fetch_url,
    parse_duckduckgo_html,
    search_web,
    text_requests_web_search,
)


DDG_HTML = """
<div class="result">
  <a class="result__a" href="https://duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fbond&amp;rut=1">铁路投标保证金</a>
  <a class="result__snippet" href="https://example.com/bond">一般不超过投标总价的 <b>2%</b></a>
</div>
<div class="result">
  <a class="result__a" href="https://example.com/notice">中标公告习惯</a>
  <a class="result__snippet">招标人常在公告中明确递交时点</a>
</div>
<a class="result__a" href="file:///etc/passwd">本地文件</a>
"""


def test_keyword_route_web_search_not_project_or_faq():
    intent, params, score = _keyword_route("联网查一下铁路投标保证金常见要求")
    assert intent == "web_search" and score >= 0.9
    assert "保证金" in params["query"]

    intent2, _, score2 = _keyword_route("帮我查这个招标人近期中标公告习惯")
    assert intent2 == "web_search" and score2 >= 0.9

    for phrase in ("网上查投标保证金", "搜索一下最新口径", "查一下最新的公开资料", "上网查资料"):
        assert text_requests_web_search(phrase)

    local_intent, _, _ = _keyword_route("找出地铁12号线标书")
    assert local_intent == "search_project"

    scored, scored_value = _score_intent("联网查一下铁路投标保证金常见要求")
    assert scored == "web_search" and scored_value >= 0.45


def test_parse_duckduckgo_html_keeps_public_links_only():
    rows = parse_duckduckgo_html(DDG_HTML)
    assert len(rows) == 2
    assert rows[0]["url"] == "https://example.com/bond"
    assert rows[0]["title"] == "铁路投标保证金"
    assert "2%" in rows[0]["snippet"]
    assert all(not item["url"].startswith("file:") for item in rows)


def test_extract_query_strips_trigger():
    assert extract_search_query("请联网查一下铁路投标保证金") == "铁路投标保证金"


def test_paid_provider_without_key_is_empty_state():
    result = asyncio.run(search_web("保证金", provider="tavily", api_key=""))
    assert result["ok"] is False
    assert result["empty_state"] is True
    assert result["results"] == []
    assert "没有填写 API Key" in result["message"]
    assert "本次没有联网检索" in result["message"]


def test_search_offline_does_not_crash(monkeypatch):
    class Boom:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, *args, **kwargs):
            raise httpx.ConnectError("offline")

    monkeypatch.setattr("app.services.web_search._httpx_client", lambda timeout=15: Boom())
    result = asyncio.run(search_web("保证金", provider="duckduckgo", api_key=""))
    assert result["ok"] is False
    assert result["offline"] is True
    assert result["results"] == []
    assert "公网" in result["message"]


def test_fetch_rejects_non_http():
    result = asyncio.run(fetch_url("file:///etc/passwd"))
    assert result["ok"] is False
    assert result["error"] == "bad_url"
    blocked = asyncio.run(fetch_url("http://127.0.0.1/secret"))
    assert blocked["ok"] is False


def test_chat_web_search_cites_and_skips_faq(monkeypatch):
    async def fake_search(query, db=None, **kwargs):
        return {
            "ok": True,
            "provider": "duckduckgo",
            "query": query,
            "results": [{
                "title": "铁路投标保证金",
                "url": "https://example.com/bond",
                "snippet": "常见要求是不超过投标总价的2%。",
            }],
            "offline": False,
            "empty_state": False,
            "error": "",
            "message": "已联网检索。",
        }

    async def fake_chat(messages, db=None, **kwargs):
        return "可参考公开资料中的比例。详见 https://evil.example/fake"

    monkeypatch.setattr("app.services.web_search.search_web", fake_search)
    monkeypatch.setattr("app.services.ai.chat_completion", fake_chat)
    faqs = [{
        "question": "铁路投标保证金常见要求",
        "answer": "这是FAQ内部答案不该被短路返回",
        "category": "投标",
        "source": "内部FAQ",
    }]
    result = asyncio.run(process_chat_message(
        "联网查一下铁路投标保证金常见要求",
        db=None,
        faq_items=faqs,
    ))
    assert result["metadata"]["intent"] == "web_search"
    assert result["metadata"]["sources"][0]["url"] == "https://example.com/bond"
    assert result["metadata"]["sources"][0]["title"] == "铁路投标保证金"
    assert "https://example.com/bond" in result["answer"]
    assert "evil.example" not in result["answer"]
    assert "这是FAQ内部答案" not in result["answer"]
    assert result.get("matched_question", "") in ("", None)


def test_chat_offline_continues_without_fake_sources(monkeypatch):
    async def fake_search(query, db=None, **kwargs):
        return {
            "ok": False,
            "provider": "duckduckgo",
            "query": query,
            "results": [],
            "offline": True,
            "empty_state": False,
            "error": "offline",
            "message": "当前无法访问公网，联网搜索没有执行成功。",
        }

    async def fake_chat(messages, db=None, **kwargs):
        return "仅根据本地资料：请核对项目里的保证金栏。"

    monkeypatch.setattr("app.services.web_search.search_web", fake_search)
    monkeypatch.setattr("app.services.ai.chat_completion", fake_chat)
    result = asyncio.run(process_chat_message(
        "网上查一下保证金",
        db=None,
        context={"web_search": True},
    ))
    assert result["metadata"]["intent"] == "web_search"
    assert result["metadata"]["sources"] == []
    assert result["metadata"]["web_search"]["offline"] is True
    assert "无法访问公网" in result["answer"]
    assert "保证金栏" in result["answer"]
    assert "http" not in result["answer"]


def test_tool_loop_web_search_returns_citations(monkeypatch):
    names = [spec["function"]["name"] for spec in TOOL_SPECS]
    assert "web_search" in names
    assert "fetch_url" in names

    async def fake_search(query, db=None, **kwargs):
        return {
            "ok": True,
            "provider": "duckduckgo",
            "query": query,
            "results": [{"title": "公告", "url": "https://example.com/notice", "snippet": "习惯"}],
            "offline": False,
            "empty_state": False,
            "error": "",
            "message": "已联网检索。",
        }

    monkeypatch.setattr("app.services.web_search.search_web", fake_search)
    result = asyncio.run(_execute_tool(
        None,
        None,
        "web_search",
        {"query": "中标公告"},
        default_project_id=None,
    ))
    assert result["ok"] is True
    assert result["results"][0]["url"] == "https://example.com/notice"


def test_toggle_context_triggers_search_without_phrase(monkeypatch):
    called = {}

    async def fake_search(query, db=None, **kwargs):
        called["query"] = query
        return {
            "ok": True,
            "provider": "duckduckgo",
            "query": query,
            "results": [{"title": "公开口径", "url": "https://example.com/p", "snippet": "摘要"}],
            "offline": False,
            "empty_state": False,
            "error": "",
            "message": "已联网检索。",
        }

    async def fake_chat(messages, db=None, **kwargs):
        return "已结合公开资料。"

    monkeypatch.setattr("app.services.web_search.search_web", fake_search)
    monkeypatch.setattr("app.services.ai.chat_completion", fake_chat)
    result = asyncio.run(process_chat_message(
        "保证金一般怎么写",
        db=None,
        context={"web_search": True},
    ))
    assert called["query"]
    assert result["metadata"]["intent"] == "web_search"
    assert result["metadata"]["sources"][0]["url"] == "https://example.com/p"
