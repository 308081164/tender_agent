"""Agent 运行时：上下文注入与 general 消息构建。"""
from __future__ import annotations

from app.services import agent_runtime


def test_build_general_messages_includes_faq_rag_not_shortcut():
    faqs = [
        {"question": "审计报告要求", "answer": "近三年的审计报告", "category": "财务"},
    ]
    msgs = agent_runtime.build_general_messages(
        "审计报告需要哪些材料",
        faqs,
        [],
        None,
    )
    assert msgs[0]["role"] == "system"
    assert "FAQ 参考片段" in msgs[0]["content"]
    assert "审计报告" in msgs[0]["content"]
    assert msgs[-1]["role"] == "user"
    assert "审计报告" in msgs[-1]["content"]


def test_resolve_project_id_from_context():
    assert agent_runtime.resolve_project_id({}, {"project_id": 42}) == 42
    assert agent_runtime.resolve_project_id({"project_id": 7}, {}) == 7
