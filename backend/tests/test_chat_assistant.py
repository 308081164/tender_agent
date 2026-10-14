"""Chat 助手意图与 FAQ 匹配测试。"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from unittest.mock import MagicMock

for _name in ("aspose", "aspose.words"):
    sys.modules.setdefault(_name, MagicMock())

from app.services.ai import _score_faq_match
from app.services.chat_assistant import _is_meta_question, process_chat_message


def test_meta_question_detection():
    assert _is_meta_question("告诉我你是谁，你能干什么")
    assert _is_meta_question("你好")
    assert not _is_meta_question("公司有哪些铁路相关资质？")


def test_faq_match_avoids_identity_false_positive():
    item = {
        "question": "是否可提供近三年审计报告？",
        "answer": "可以，我公司可提供近三年完整审计报告。",
        "category": "财务类",
        "source": "财务_近三年审计报告_2025.docx",
    }
    score = _score_faq_match("告诉我你是谁，你能干什么", item)
    assert score < 0.35


def test_faq_match_hits_domain_question():
    item = {
        "question": "是否具备铁路工程施工总承包资质？",
        "answer": "具备壹级资质。",
        "category": "资质类",
        "source": "",
    }
    score = _score_faq_match("公司有哪些铁路相关资质？", item)
    assert score >= 0.35


def test_fallback_and_project_links_do_not_send_users_to_removed_workspace(monkeypatch):
    """答非所问和项目链接不再写出「打开/进入创作工作台」，也不再指向该页面。"""
    from app.services.agent_query_tools import _project_brief
    from app.services.chat_assistant import _handle_draft_create, _handle_edit_project

    async def empty(messages, db=None, **kwargs):
        return ""

    monkeypatch.setattr("app.services.ai.chat_completion", empty)

    class _Project:
        id = 7
        title = "新建标书"
        current_step = 3
        status = "draft"
        fields = {}
        created_at = None
        updated_at = None

    monkeypatch.setattr("app.services.chat_assistant._latest_project", lambda db: _Project())

    fallback = asyncio.run(process_chat_message("zzz无关问题", db=None, faq_items=[]))
    draft = asyncio.run(_handle_draft_create(None))
    edited = asyncio.run(_handle_edit_project(None))
    brief = _project_brief(_Project(), None)
    blobs = [
        fallback["answer"],
        draft["answer"],
        edited["answer"],
        brief["edit_url"],
    ]
    for item in (fallback, draft, edited):
        blobs.append(__import__("json").dumps(item.get("metadata") or {}, ensure_ascii=False))
    text = "\n".join(blobs)
    assert "创作工作台" not in text
    assert "/workspace" not in text
    assert "暂未匹配到明确答案" in fallback["answer"]
    assert "打开 Agent 对话" in text


def test_process_meta_question_without_llm():
    async def _run():
        with __import__("unittest.mock").mock.patch(
            "app.services.chat_assistant._classify_intent",
            return_value="general",
        ):
            result = await process_chat_message("你是谁", db=None, faq_items=[])
        assert result["metadata"]["intent"] == "meta"
        assert "标书智能体" in result["answer"]
        assert "审计报告" not in result["answer"]

    asyncio.run(_run())


if __name__ == "__main__":
    test_meta_question_detection()
    test_faq_match_avoids_identity_false_positive()
    test_faq_match_hits_domain_question()
    test_process_meta_question_without_llm()
    print("PASS all chat assistant tests")
