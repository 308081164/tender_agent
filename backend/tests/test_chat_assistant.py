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
