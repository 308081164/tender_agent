"""能力 1–9 固定任务回归。不访问公网，不启动 OnlyOffice。

运行：
    cd backend && python -m pytest tests/test_agent_capability_regression.py -q
前端辅助断言：
    cd frontend && node --test src/components/chat/agentChatRuntime.test.js src/components/chat/chatTranscriptModel.test.js
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ["AGENT_TOOL_LOOP"] = "1"

from unittest.mock import MagicMock

for _name in ("aspose", "aspose.words"):
    sys.modules.setdefault(_name, MagicMock())

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.models import ChatSession, CompanyProfile, FieldDef, TenderProject
from app.routers import api as api_router
from app.services.agent_capabilities import (
    ANCHOR_MISSING,
    MAX_TOOL_STEPS,
    apply_project_field_patch,
    check_against_tender,
    extract_decision,
    fix_review_issue,
    interrupted_answer,
    mention_prompt_block,
    normalize_mentions,
    parse_tender_text,
    remember_decision,
    resolve_document_anchor,
    side_question_kind,
    tool_loop_default_on,
)
from app.services.agent_runtime import build_general_messages
from app.services.agent_tool_loop import TOOL_SPECS, run_tool_loop, tool_loop_enabled
from app.services.chat_assistant import _handle_edit_fragment, _handle_insert_image, _handle_insert_table
from app.services.project_context import build_field_checklist
from app.services.project_export_flow import try_handle_export_flow

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
Base.metadata.create_all(engine)
TestSession = sessionmaker(bind=engine)
app = FastAPI()
app.include_router(api_router.router, prefix="/api")


def _override_get_db():
    db = TestSession()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = _override_get_db
client = TestClient(app)


def _db():
    return TestSession()


def _project(db, **kwargs):
    project = TenderProject(title=kwargs.pop("title", "演示标书"), current_step=kwargs.pop("current_step", 3), **kwargs)
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def _field(db, key, **kwargs):
    row = db.query(FieldDef).filter(FieldDef.key == key).first()
    if row:
        return row
    row = FieldDef(key=key, name=kwargs.pop("name", key), template_code="common", **kwargs)
    db.add(row)
    db.commit()
    return row


def test_tool_loop_defaults_on_and_lists_required_tools(monkeypatch):
    monkeypatch.delenv("AGENT_TOOL_LOOP", raising=False)
    assert tool_loop_default_on() is True
    assert tool_loop_enabled() is True
    names = {spec["function"]["name"] for spec in TOOL_SPECS}
    assert names >= {
        "read_workspace_file",
        "write_workspace_file",
        "read_project_attachment",
        "read_tender_excerpt",
        "update_project_fields",
        "edit_document_anchor",
        "web_search",
        "fetch_url",
        "get_preview_status",
        "check_against_tender",
    }
    assert MAX_TOOL_STEPS == 8


def test_stream_emits_tokens_before_done_and_keeps_partial_on_error(monkeypatch):
    async def fake_completion(messages, db=None, **kwargs):
        return ""

    async def fake_stream(messages, db=None, **kwargs):
        yield "已经写出"
        raise RuntimeError("模型连接中断")

    monkeypatch.setattr("app.services.ai.chat_completion", fake_completion)
    monkeypatch.setattr("app.services.ai.chat_completion_stream", fake_stream)
    monkeypatch.setattr("app.services.agent_tool_loop._chat_with_tools", fake_completion)

    created = client.post("/api/chat/sessions", json={"title": "stream"})
    sid = created.json()["id"]
    events = []
    with client.stream(
        "POST",
        f"/api/chat/sessions/{sid}/messages/stream",
        json={"content": "请把施工组织写得更顺一些"},
    ) as resp:
        assert resp.status_code == 200
        buf = ""
        for chunk in resp.iter_text():
            buf += chunk
            while "\n\n" in buf:
                part, buf = buf.split("\n\n", 1)
                if part.strip().startswith("data:"):
                    events.append(json.loads(part.strip()[5:]))
    kinds = [item["type"] for item in events]
    assert kinds.index("token") < kinds.index("error")
    assert events[kinds.index("token")]["text"] == "已经写出"
    assert "模型连接中断" in events[kinds.index("error")]["message"]
    done = events[kinds.index("done")]["payload"]
    answer = done["assistant_message"]["content"]
    assert "已经写出" in answer
    assert "模型连接中断" in answer
    assert interrupted_answer("已经写出", "模型连接中断") == answer or "已经写出" in answer


def test_tool_loop_stops_at_eight_and_trace_is_visible(monkeypatch):
    calls = {"n": 0}

    async def always_tools(messages, db=None):
        calls["n"] += 1
        return {
            "choices": [{
                "message": {
                    "content": "",
                    "tool_calls": [{
                        "id": f"c{calls['n']}",
                        "type": "function",
                        "function": {"name": "get_preview_status", "arguments": "{}"},
                    }],
                }
            }]
        }

    monkeypatch.setattr("app.services.agent_tool_loop._chat_with_tools", always_tools)
    session = ChatSession(title="loop", workspace={})
    result = asyncio.run(run_tool_loop(
        db=_db(),
        session=session,
        messages=[{"role": "user", "content": "看预览"}],
        workspace={},
        context={},
    ))
    assert result is not None
    assert len(result["metadata"]["tool_trace"]) == 8
    assert calls["n"] == 8
    assert "get_preview_status" in result["answer"]
    assert "调用了工具" in result["answer"]


def test_fill_fields_does_not_reverify_unchanged_step2_values():
    db = _db()
    _field(db, "duration", name="工期", field_type="文本", module="工期与服务")
    _field(db, "project_name", name="项目名称", field_type="文本")
    project = _project(db, fields={"duration": "180天", "project_name": "旧名称"}, current_step=3)
    applied = apply_project_field_patch(db, project, {"project_name": "新名称", "duration": "180天"})
    db.commit()
    db.refresh(project)
    assert applied["updated_keys"] == ["project_name"]
    assert "duration" not in (project.fields.get("_field_reverify") or [])
    verify_keys = [item["key"] for item in build_field_checklist(db, project)["needs_verify"]]
    assert "duration" not in verify_keys
    db.close()


def test_memo_is_recalled_and_does_not_reopen_step2_fields():
    db = _db()
    _field(db, "duration", name="工期", field_type="文本", module="工期与服务", required=True)
    project = _project(db, fields={"duration": "12个月"}, current_step=3)
    assert extract_decision("报价以招标文件为准")
    assert extract_decision("这章先不写人员")
    remember_decision(project, "报价以招标文件为准")
    remember_decision(project, "这章先不写人员")
    db.commit()
    db.refresh(project)
    assert "duration" not in (project.fields.get("_field_reverify") or [])
    verify_keys = [item["key"] for item in build_field_checklist(db, project)["needs_verify"]]
    assert "duration" not in verify_keys
    messages = build_general_messages(
        "下一章写什么",
        [],
        [],
        db,
        workspace={"project_id": project.id},
        context={"project_id": project.id},
    )
    system = messages[0]["content"]
    assert "报价以招标文件为准" in system
    assert "这章先不写人员" in system
    db.close()


def test_pending_flow_answers_readonly_and_blocks_writes():
    db = _db()
    db.add(CompanyProfile(id=1, full_name="和远智能股份有限公司"))
    project = _project(db)
    session = ChatSession(title="flow", workspace={
        "project_id": project.id,
        "pending_action": {"flow": "qual_folder_import", "stage": "confirm_scan"},
    })
    db.add(session)
    db.commit()
    db.refresh(session)
    sid = session.id
    db.close()

    progress = client.post(f"/api/chat/sessions/{sid}/messages", json={"content": "现在进行到哪一步"})
    assert progress.status_code == 200
    assert "进度" in progress.json()["answer"]
    assert "取消" in progress.json()["answer"]

    company = client.post(f"/api/chat/sessions/{sid}/messages", json={"content": "公司全称是什么"})
    assert "和远智能股份有限公司" in company.json()["answer"]

    blocked = client.post(f"/api/chat/sessions/{sid}/messages", json={"content": "确认导入"})
    assert "取消" in blocked.json()["answer"]
    assert blocked.json()["metadata"].get("blocked_write") is True

    loaded = client.get(f"/api/chat/sessions/{sid}")
    pending = loaded.json()["workspace"]["pending_action"]
    assert pending["flow"] == "qual_folder_import"
    assert side_question_kind("联网查一下保证金", {}) == "readonly"


def test_tender_file_is_context_and_check_tool_finds_conflict():
    text = "\n".join([
        "评分办法：技术方案 40 分",
        "工期要求：180天",
        "资质要求：市政公用工程施工总承包一级",
        "投标截止时间：2026-11-02",
        "出现违法分包的，按废标处理，不得转包",
    ])
    parsed = parse_tender_text(text)
    assert parsed["duration"] == "180天"
    assert parsed["scoring_points"]
    assert parsed["disqualification"]
    assert parsed["qualifications"]
    assert parsed["key_dates"]
    conflict = check_against_tender("本项目工期90天，且不得转包。", parsed)
    assert conflict["ok"] is False
    assert any(item["kind"] == "duration" for item in conflict["conflicts"])
    assert any(item["kind"] == "disqualification" for item in conflict["conflicts"])

    db = _db()
    project = _project(db, fields={})
    db.close()
    uploaded = client.post(
        f"/api/projects/{project.id}/tender-file",
        files={"file": ("招标文件.txt", text.encode("utf-8"), "text/plain")},
    )
    assert uploaded.status_code == 200
    body = uploaded.json()["tender"]
    assert body["duration"] == "180天"
    ctx = client.get(f"/api/projects/{project.id}/context")
    assert ctx.status_code == 200
    assert ctx.json()["tender"]["duration"] == "180天"
    assert "180天" in ctx.json()["tender_prompt"]


def test_anchor_is_required_for_rewrite_table_and_image():
    missing = asyncio.run(_handle_insert_table(
        "插入表格 3x2",
        {},
        {"draft_object_key": "drafts/a.docx"},
    ))
    assert missing["answer"] == ANCHOR_MISSING
    assert "needs_workspace_insert_table" not in missing["metadata"]

    placed = asyncio.run(_handle_insert_table(
        "插入表格 3x2",
        {"paragraph_index": 4, "block_id": "section:4"},
        {"draft_object_key": "drafts/a.docx"},
    ))
    assert placed["metadata"]["paragraph_index"] == 4
    assert placed["metadata"]["paragraph_index"] != 0

    image = asyncio.run(_handle_insert_image(
        "插入图片",
        {"attachment_object_key": "img/a.png"},
        {"draft_object_key": "drafts/a.docx"},
    ))
    assert image["answer"] == ANCHOR_MISSING

    edit = asyncio.run(_handle_edit_fragment("改为更正式", {}))
    assert edit["answer"] == ANCHOR_MISSING
    anchored = asyncio.run(_handle_edit_fragment("改为更正式", {"selected_text": "工期90天", "paragraph_index": 2}))
    assert anchored["metadata"]["paragraph_index"] == 2
    assert anchored["metadata"]["selected_text"] == "工期90天"
    assert resolve_document_anchor({})["ok"] is False
    assert resolve_document_anchor({"paragraph_index": 0})["paragraph_index"] == 0


def test_mentions_enter_the_prompt():
    mentions = normalize_mentions([
        {"kind": "file", "label": "技术方案.txt", "path": "技术方案.txt"},
        {"kind": "section", "label": "评分办法", "section_id": "tender-score:0"},
    ])
    block = mention_prompt_block(mentions)
    assert "技术方案.txt" in block
    assert "评分办法" in block
    db = _db()
    project = _project(db, chapters={"施工组织": {"content": "正文"}})
    session = ChatSession(title="at", workspace={"project_id": project.id})
    db.add(session)
    db.commit()
    sid = session.id
    db.close()
    listed = client.get(f"/api/chat/sessions/{sid}/mentions?q=施工")
    assert listed.status_code == 200
    labels = [item["label"] for item in listed.json()["items"]]
    assert "施工组织" in labels


def test_click_or_say_fix_reviews_only_that_issue():
    db = _db()
    project = _project(
        db,
        chapters={"_plain": "计划工期 90天。另有未盖章页。"},
        checklist_result={"doc_review": {"issues": [
            {"message": "工期冲突「90天」", "excerpt": "90天", "suggestion": "180天"},
            {"message": "缺少印章「未盖章」", "excerpt": "未盖章", "suggestion": "已盖章"},
        ]}},
    )
    db.commit()
    fixed = fix_review_issue(project, "rv-1")
    db.commit()
    db.refresh(project)
    assert fixed["resolved"] is True
    assert "180天" in project.chapters["_plain"]
    assert "未盖章" in project.chapters["_plain"]
    assert "90天" not in fixed["highlight_texts"]
    assert "未盖章" in fixed["highlight_texts"]
    assert fixed["rereview"]["issue_id"] == "rv-1"
    db.close()


def test_export_wording_web_citation_and_memo_roundtrip(monkeypatch):
    class Dummy:
        workspace = {"project_id": 1, "export_flow": "awaiting_user_ack"}

    export = asyncio.run(try_handle_export_flow("请再确认一下", None, Dummy(), Dummy.workspace))
    assert "可以导出" in export["answer"] or "没问题了" in export["answer"]

    async def scripted(messages, db=None):
        last = messages[-1]
        if last.get("role") == "tool":
            return {"choices": [{"message": {"content": "见 https://example.com/notice ，不要看 https://evil.example/x"}}]}
        return {"choices": [{"message": {"tool_calls": [{
            "id": "w1",
            "type": "function",
            "function": {"name": "web_search", "arguments": json.dumps({"query": "保证金"})},
        }]}}]}

    async def fake_search(query, db=None, **kwargs):
        return {
            "ok": True,
            "provider": "fixture",
            "query": query,
            "results": [{"title": "公告", "url": "https://example.com/notice", "snippet": "习惯"}],
            "offline": False,
            "message": "已联网检索。",
        }

    monkeypatch.setattr("app.services.agent_tool_loop._chat_with_tools", scripted)
    monkeypatch.setattr("app.services.web_search.search_web", fake_search)
    found = asyncio.run(run_tool_loop(
        db=_db(),
        session=ChatSession(title="web", workspace={}),
        messages=[{"role": "user", "content": "联网查保证金"}],
        workspace={},
        context={},
    ))
    assert "https://example.com/notice" in found["answer"]
    assert "evil.example" not in found["answer"]
    assert found["metadata"]["tool_trace"][0]["tool"] == "web_search"

    db = _db()
    project = _project(db)
    pid = project.id
    session = ChatSession(title="memo", workspace={"project_id": pid})
    db.add(session)
    db.commit()
    sid = session.id
    db.close()
    saved = client.post(f"/api/chat/sessions/{sid}/messages", json={"content": "报价以招标文件为准"})
    assert saved.status_code == 200
    assert "已写入项目备忘" in saved.json()["answer"]
    memos = client.get(f"/api/projects/{pid}/memos")
    memo_id = memos.json()["memos"][0]["id"]
    deleted = client.delete(f"/api/projects/{pid}/memos/{memo_id}")
    assert deleted.status_code == 200
    assert deleted.json()["memos"] == []
