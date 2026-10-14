"""能力 1–9 深度回归：执行真实函数，只替掉模型 HTTP 和公网检索。

运行：
    cd backend && python -m pytest tests/test_agent_capability_depth.py -q
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ["AGENT_TOOL_LOOP"] = "1"

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.models import ChatSession, CompanyProfile, Qualification, TenderProject
from app.routers import api as api_router
from app.services.agent_capabilities import (
    ANCHOR_MISSING,
    check_against_tender,
    extract_decision,
    mention_candidates,
)
from app.services.docx_ooxml import build_docx, document_text, insert_image, insert_table, plain_text
from app.services import storage as storage_mod

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
BLOB = {}


def _db():
    return TestSession()


def _project(db, **kwargs):
    project = TenderProject(title=kwargs.pop("title", "深度标书"), current_step=kwargs.pop("current_step", 3), **kwargs)
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def _session(db, workspace):
    row = ChatSession(title="depth", workspace=workspace)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _patch_llm(monkeypatch):
    monkeypatch.setattr("app.services.ai.pick_model", lambda *args, **kwargs: ["fake"])
    monkeypatch.setattr(
        "app.services.ai._provider_call",
        lambda *args, **kwargs: ("http://llm.test/v1", "k", "m"),
    )


def _sse(chunks):
    lines = []
    for chunk in chunks:
        lines.append("data: " + json.dumps({"choices": [{"delta": chunk}]}, ensure_ascii=False))
    lines.append("data: [DONE]")
    return lines


class _Stream:
    def __init__(self, lines, boom_after=None):
        self.lines = lines
        self.boom_after = boom_after
        self.status_code = 200

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def raise_for_status(self):
        return None

    async def aiter_lines(self):
        sent = 0
        for line in self.lines:
            if self.boom_after is not None and sent >= self.boom_after:
                raise RuntimeError("模型连接中断")
            yield line
            if '"content"' in line:
                sent += 1


class _Resp:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _install_http(monkeypatch, planner):
    class Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        def stream(self, method, url, headers=None, json=None):
            return _Stream(*planner(json or {}, stream=True))

        async def post(self, url, headers=None, json=None):
            lines, payload = planner(json or {}, stream=False)
            return _Resp(payload or {"choices": [{"message": {"content": "180天"}}]})

    monkeypatch.setattr("httpx.AsyncClient", Client)


def _memory_storage(monkeypatch):
    def upload(key, data, content_type="application/octet-stream"):
        BLOB[key] = bytes(data)
        return key

    def download(key):
        if key not in BLOB:
            raise FileNotFoundError(key)
        return BLOB[key]

    monkeypatch.setattr(storage_mod, "upload_bytes", upload)
    monkeypatch.setattr(storage_mod, "download_bytes", download)
    monkeypatch.setattr("app.services.storage.upload_bytes", upload)
    monkeypatch.setattr("app.services.storage.download_bytes", download)


def test_tool_loop_streams_model_deltas_and_keeps_partial(monkeypatch):
    _patch_llm(monkeypatch)
    state = {"n": 0}

    def planner(payload, stream):
        state["n"] += 1
        if state["n"] == 1:
            return _sse([{"content": "已"}, {"content": "经写出"}]), None
        return _sse([{"content": "不会走到"}]), None

    class BoomClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        def stream(self, method, url, headers=None, json=None):
            return _Stream(_sse([{"content": "已经写出"}]), boom_after=1)

        async def post(self, url, headers=None, json=None):
            return _Resp({"choices": [{"message": {"content": ""}}]})

    monkeypatch.setattr("httpx.AsyncClient", BoomClient)
    db = _db()
    session = _session(db, {})
    sid = session.id
    db.close()
    events = []
    with client.stream("POST", f"/api/chat/sessions/{sid}/messages/stream", json={"content": "随便聊聊工期"}) as resp:
        assert resp.status_code == 200
        buf = ""
        for chunk in resp.iter_text():
            buf += chunk
            while "\n\n" in buf:
                part, buf = buf.split("\n\n", 1)
                if part.strip().startswith("data:"):
                    events.append(json.loads(part.strip()[5:]))
    tokens = [item["text"] for item in events if item["type"] == "token"]
    assert tokens == ["已经写出"]
    assert any(item["type"] == "error" and "模型连接中断" in item["message"] for item in events)
    done = next(item["payload"] for item in events if item["type"] == "done")
    assert "已经写出" in done["assistant_message"]["content"]
    assert "模型连接中断" in done["assistant_message"]["content"]


def test_edit_and_insert_tools_change_docx_inside_the_loop(monkeypatch):
    _patch_llm(monkeypatch)
    _memory_storage(monkeypatch)
    seen = []

    def planner(payload, stream):
        seen.append(payload)
        choice = (payload.get("tool_choice") or {})
        name = ((choice.get("function") or {}).get("name")) if isinstance(choice, dict) else ""
        if name == "edit_document_anchor":
            args = json.dumps({"instruction": "改为180天"}, ensure_ascii=False)
            return _sse([
                {"tool_calls": [{"index": 0, "id": "e1", "function": {"name": "edit_document_anchor", "arguments": args}}]},
            ]), None
        if name == "insert_table":
            args = json.dumps({"rows": 2, "cols": 2}, ensure_ascii=False)
            return _sse([
                {"tool_calls": [{"index": 0, "id": "t1", "function": {"name": "insert_table", "arguments": args}}]},
            ]), None
        if name == "insert_image":
            args = json.dumps({}, ensure_ascii=False)
            return _sse([
                {"tool_calls": [{"index": 0, "id": "i1", "function": {"name": "insert_image", "arguments": args}}]},
            ]), None
        if not stream:
            return [], {"choices": [{"message": {"content": "180天"}}]}
        return _sse([{"content": "已"}, {"content": "按锚点改完"}]), None

    _install_http(monkeypatch, planner)
    db = _db()
    project = _project(db, fields={"_agent_memos": [{"id": "m1", "text": "报价以招标文件为准"}]})
    doc = build_docx(["封面", "计划工期 90天"])
    BLOB["drafts/base.docx"] = doc
    BLOB["img/a.png"] = b"\x89PNG\r\n\x1a\n"
    session = _session(db, {"project_id": project.id, "draft_object_key": "drafts/base.docx"})
    sid = session.id
    pid = project.id
    db.close()

    edited = client.post(f"/api/chat/sessions/{sid}/messages", json={
        "content": "改写这段工期",
        "context": {"selected_text": "90天", "paragraph_index": 1, "project_id": pid},
    })
    assert edited.status_code == 200
    body = edited.json()
    assert any(item["tool"] == "edit_document_anchor" for item in body["metadata"]["tool_trace"])
    assert "报价以招标文件为准" in json.dumps(seen, ensure_ascii=False)
    key = body["metadata"].get("draft_object_key") or body["session"]["workspace"]["draft_object_key"]
    assert "180天" in plain_text(BLOB[key])
    assert "90天" not in plain_text(BLOB[key])

    missing = client.post("/api/chat/sessions", json={"title": "no-anchor"})
    mid = missing.json()["id"]
    db = _db()
    row = db.query(ChatSession).filter(ChatSession.id == mid).first()
    row.workspace = {"project_id": pid, "draft_object_key": key}
    db.commit()
    db.close()
    refused = client.post(f"/api/chat/sessions/{mid}/messages", json={"content": "插入表格 2x2"})
    assert ANCHOR_MISSING in refused.json()["answer"]

    placed = client.post(f"/api/chat/sessions/{sid}/messages", json={
        "content": "插入表格 2x2",
        "context": {"paragraph_index": 1, "project_id": pid},
    })
    assert any(item["tool"] == "insert_table" for item in placed.json()["metadata"]["tool_trace"])
    table_key = placed.json()["session"]["workspace"]["draft_object_key"]
    from zipfile import ZipFile
    from io import BytesIO
    with ZipFile(BytesIO(BLOB[table_key])) as archive:
        xml = archive.read("word/document.xml").decode("utf-8")
    assert "<w:tbl" in xml or "w:tbl" in xml

    imaged = client.post(f"/api/chat/sessions/{sid}/messages", json={
        "content": "插入图片",
        "context": {"paragraph_index": 1, "attachment_object_key": "img/a.png", "project_id": pid},
    })
    assert any(item["tool"] == "insert_image" for item in imaged.json()["metadata"]["tool_trace"])
    image_key = imaged.json()["session"]["workspace"]["draft_object_key"]
    with ZipFile(BytesIO(BLOB[image_key])) as archive:
        assert "word/media/image1.png" in archive.namelist()
        rels = archive.read("word/_rels/document.xml.rels").decode("utf-8")
    assert "rIdImage1" in rels


def test_memo_reaches_rewrite_web_and_semantic(monkeypatch):
    assert extract_decision("人员配置就按项目经理负责")
    assert extract_decision("报价口径是下浮3个点")
    assert extract_decision("工期到底是多少？") is None
    captured = []

    async def fake_complete(messages, db=None, **kwargs):
        captured.append(messages)
        return "已按备忘回答"

    async def fake_search(query, db=None, **kwargs):
        return {"ok": True, "provider": "fixture", "query": query, "results": [
            {"title": "公告", "url": "https://example.com/notice", "snippet": "习惯"},
        ], "offline": False, "message": "已联网检索。"}

    monkeypatch.setattr("app.services.ai.chat_completion", fake_complete)
    monkeypatch.setattr("app.services.web_search.search_web", fake_search)
    db = _db()
    project = _project(db, fields={"_agent_memos": [{"id": "m9", "text": "这章先不写人员"}]})
    pid = project.id
    db.add(CompanyProfile(id=1, full_name="和远智能股份有限公司"))
    db.commit()
    from app.services.web_search import run_web_research
    from app.services.agent_semantic import process_with_semantic_router
    import asyncio

    asyncio.run(run_web_research("联网查保证金", db, workspace={"project_id": pid}, context={"project_id": pid}))
    asyncio.run(process_with_semantic_router(
        "公司全称是什么", db, [], [], workspace={"project_id": pid}, context={"project_id": pid},
    ))
    blob = json.dumps(captured, ensure_ascii=False)
    assert blob.count("这章先不写人员") >= 2
    db.close()


def test_pending_personnel_query_and_revision_write_block():
    db = _db()
    if not db.query(CompanyProfile).filter(CompanyProfile.id == 1).first():
        db.add(CompanyProfile(id=1, full_name="和远智能股份有限公司", legal_name="李四"))
    db.add(Qualification(category="人员", name="张三", object_key="q/zhang", keywords="项目经理"))
    project = _project(db, fields={"project_manager": "张三"})
    session = _session(db, {
        "project_id": project.id,
        "pending_action": {"flow": "project_create", "stage": "revise_document"},
        "draft_object_key": "drafts/rev.docx",
    })
    BLOB["drafts/rev.docx"] = build_docx(["原文不动"])
    sid = session.id
    db.commit()
    db.close()
    people = client.post(f"/api/chat/sessions/{sid}/messages", json={"content": "查一下人员"})
    answer = people.json()["answer"]
    assert "张三" in answer
    assert "公司全称：和远智能股份有限公司" != answer.strip()
    blocked = client.post(f"/api/chat/sessions/{sid}/messages", json={"content": "确认导入"})
    assert blocked.json()["metadata"]["blocked_write"] is True
    loaded = client.get(f"/api/chat/sessions/{sid}")
    assert loaded.json()["workspace"]["pending_action"]["stage"] == "revise_document"


def test_check_against_tender_covers_score_qualification_and_date(monkeypatch):
    _patch_llm(monkeypatch)
    seen = []
    real = check_against_tender

    def wrapped(draft, tender):
        out = real(draft, tender)
        seen.append(out)
        return out

    monkeypatch.setattr("app.services.agent_tool_loop.check_against_tender", wrapped)

    def planner(payload, stream):
        choice = payload.get("tool_choice") or {}
        name = (choice.get("function") or {}).get("name") if isinstance(choice, dict) else ""
        if name == "check_against_tender":
            args = json.dumps({"text": "投标截止时间：2026-12-01。资质写了二级。工期180天。"}, ensure_ascii=False)
            return _sse([
                {"tool_calls": [{"index": 0, "id": "c1", "function": {"name": "check_against_tender", "arguments": args}}]},
            ]), None
        return _sse([{"content": "对照完了"}]), None

    _install_http(monkeypatch, planner)
    db = _db()
    project = _project(db, fields={"_tender": {
        "duration": "180天",
        "scoring_points": ["评分办法：技术方案 40 分"],
        "qualifications": ["资质要求：市政公用工程施工总承包一级"],
        "key_dates": ["2026-11-02"],
        "disqualification": [],
    }})
    session = _session(db, {"project_id": project.id})
    sid = session.id
    db.close()
    sent = client.post(f"/api/chat/sessions/{sid}/messages", json={"content": "对照招标文件看这段"})
    assert sent.status_code == 200
    assert any(item["tool"] == "check_against_tender" for item in sent.json()["metadata"]["tool_trace"])
    kinds = {item["kind"] for item in seen[0]["conflicts"]}
    assert {"scoring", "qualification", "date"} <= kinds


def test_nested_mention_is_the_rewrite_target(monkeypatch):
    _patch_llm(monkeypatch)
    root = Path("/tmp/tender-depth-ws")
    nested = root / "过程资料" / "章节"
    nested.mkdir(parents=True, exist_ok=True)
    target = nested / "技术方案.txt"
    target.write_text("工期90天", encoding="utf-8")

    def planner(payload, stream):
        choice = payload.get("tool_choice") or {}
        name = (choice.get("function") or {}).get("name") if isinstance(choice, dict) else ""
        if name == "edit_document_anchor":
            args = json.dumps({"instruction": "改成180天"}, ensure_ascii=False)
            return _sse([
                {"tool_calls": [{"index": 0, "id": "f1", "function": {"name": "edit_document_anchor", "arguments": args}}]},
            ]), None
        if not stream:
            return [], {"choices": [{"message": {"content": "工期180天"}}]}
        return _sse([{"content": "已改文件"}]), None

    _install_http(monkeypatch, planner)
    db = _db()
    project = _project(db)
    session = _session(db, {"project_id": project.id, "workspace_dir": str(root)})
    labels = [item["path"] for item in mention_candidates(db, session, "技术")]
    assert "过程资料/章节/技术方案.txt" in labels
    sid = session.id
    db.close()
    sent = client.post(f"/api/chat/sessions/{sid}/messages", json={
        "content": "改写这段",
        "context": {"mentions": [{
            "kind": "file",
            "label": "技术方案.txt",
            "path": "过程资料/章节/技术方案.txt",
        }]},
    })
    assert sent.status_code == 200
    assert "180天" in target.read_text(encoding="utf-8")


def test_review_fix_patches_docx_and_rereviews_that_issue(monkeypatch):
    async def no_llm(*args, **kwargs):
        return "[]"

    monkeypatch.setattr("app.services.ai.chat_completion", no_llm)
    from app.services.doc_engine.review import review_document
    from app.services.agent_capabilities import fix_review_issue
    import asyncio

    doc = build_docx(["计划工期 90天。另有未盖章页。"])
    review = asyncio.run(review_document(
        doc,
        {"duration": "180天"},
        None,
        {"fields": {"duration": {"value": "90天"}}},
        [],
        db=None,
    ))
    issue = next(item for item in review["issues"] if item.get("code") == "stale_value")
    assert issue["excerpt"] == "90天"
    assert issue["suggestion"] == "180天"
    db = _db()
    project = _project(db, chapters={"_plain": "计划工期 90天。另有未盖章页。"}, checklist_result={"doc_review": review})
    fixed = asyncio.run(fix_review_issue(project, issue["id"], docx_bytes=doc, db=db))
    db.commit()
    assert fixed["rereview"]["checked_on"] == "review_document"
    assert fixed["rereview"]["ok"] is True
    assert "180天" in plain_text(fixed["docx_bytes"])
    assert "90天" not in plain_text(fixed["docx_bytes"])
    assert "未盖章" in plain_text(fixed["docx_bytes"])
    db.close()


def test_insert_image_lands_after_selected_paragraph():
    doc = build_docx(["第一段", "第二段", "第三段"])
    png = b"\x89PNG\r\n\x1a\n"
    updated = insert_image(doc, 1, png)
    text = plain_text(updated)
    assert text.split("\n")[0] == "第一段"
    from zipfile import ZipFile
    from io import BytesIO
    with ZipFile(BytesIO(updated)) as archive:
        assert "word/media/image1.png" in archive.namelist()
        rels = archive.read("word/_rels/document.xml.rels").decode("utf-8")
    assert "rIdImage1" in rels


def test_pending_readonly_reads_file_and_searches_web(monkeypatch):
    async def fake_search(query, db=None, **kwargs):
        return {
            "ok": True,
            "provider": "fixture",
            "query": query,
            "results": [{"title": "保证金公告", "url": "https://example.com/bond", "snippet": "公开要求"}],
            "offline": False,
            "message": "已联网检索。",
        }

    monkeypatch.setattr("app.services.web_search.search_web", fake_search)
    root = Path("/tmp/tender-depth-read")
    root.mkdir(parents=True, exist_ok=True)
    target = root / "技术方案.txt"
    target.write_text("工期180天", encoding="utf-8")
    db = _db()
    project = _project(db)
    session = _session(db, {
        "project_id": project.id,
        "workspace_dir": str(root),
        "pending_action": {"flow": "project_create", "stage": "revise_document"},
    })
    sid = session.id
    db.close()
    read = client.post(f"/api/chat/sessions/{sid}/messages", json={"content": "读一下文件 技术方案.txt"})
    assert read.status_code == 200
    assert "180天" in read.json()["answer"]
    assert read.json()["metadata"]["readonly"] is True
    searched = client.post(f"/api/chat/sessions/{sid}/messages", json={"content": "联网查一下投标保证金"})
    assert "保证金公告" in searched.json()["answer"]
    loaded = client.get(f"/api/chat/sessions/{sid}")
    assert loaded.json()["workspace"]["pending_action"]["stage"] == "revise_document"
    assert target.read_text(encoding="utf-8") == "工期180天"


def test_docx_tender_table_is_parsed_and_pdf_bytes_are_not_text():
    doc = insert_table(
        build_docx(["投标说明"]),
        0,
        cells=[
            ["评分办法：技术方案 40 分"],
            ["资质要求：市政公用工程施工总承包一级"],
            ["投标截止时间 2026-11-02"],
            ["工期 180天"],
        ],
    )
    assert "技术方案" not in plain_text(doc)
    assert "技术方案" in document_text(doc)
    db = _db()
    project = _project(db)
    pid = project.id
    db.close()
    uploaded = client.post(
        f"/api/projects/{pid}/tender-file",
        files={"file": ("tender.docx", doc, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )
    assert uploaded.status_code == 200
    tender = uploaded.json()["tender"]

    def shown(item):
        return json.dumps(item, ensure_ascii=False) if isinstance(item, dict) else str(item)

    assert any(item.get("title") == "技术方案" and str(item.get("source") or "").startswith("table:") for item in tender["scoring_points"])
    assert any("市政公用" in shown(item) for item in tender["qualifications"])
    assert any("2026-11-02" in shown(item) for item in tender["key_dates"])
    checked = check_against_tender("投标截止时间：2026-12-01。资质写了二级。工期180天。", tender)
    failed = {item["item"] for item in checked["conflicts"]}
    assert "技术方案" in failed
    assert any("市政公用" in name for name in failed)
    assert any("投标截止" in name for name in failed)
    noise = client.post(
        f"/api/projects/{pid}/tender-file",
        files={"file": ("noise.pdf", "\xff\xfe评分办法".encode("utf-8", errors="surrogateescape"), "application/pdf")},
    )
    assert noise.status_code == 200
    assert not any("评分" in shown(item) for item in noise.json()["tender"]["scoring_points"])


def test_workspace_fix_passes_open_docx_and_reruns_review(monkeypatch):
    async def no_llm(*args, **kwargs):
        return "[]"

    monkeypatch.setattr("app.services.ai.chat_completion", no_llm)
    _memory_storage(monkeypatch)
    doc = build_docx(["计划工期 90天。", "另有未盖章页。"])
    BLOB["projects/open.docx"] = doc
    db = _db()
    project = _project(db, fields={
        "duration": "180天",
        "_draft_object_key": "projects/open.docx",
    }, checklist_result={"doc_review": {"issues": [{
        "id": "rv-9",
        "code": "stale_value",
        "field": "duration",
        "message": "文档中仍残留旧工期",
        "suggestion": "180天",
    }]}})
    session = _session(db, {"project_id": project.id, "draft_object_key": "projects/open.docx"})
    pid = project.id
    sid = session.id
    db.commit()
    db.close()
    fixed = client.post(f"/api/projects/{pid}/review-issues/rv-9/fix")
    assert fixed.status_code == 200
    body = fixed.json()
    assert body["rereview"]["checked_on"] == "review_document"
    assert body["ok"] is True
    key = body["draft_object_key"]
    assert "180天" in plain_text(BLOB[key])
    assert "90天" not in plain_text(BLOB[key])
    assert "未盖章" in plain_text(BLOB[key])
    loaded = client.get(f"/api/chat/sessions/{sid}")
    assert loaded.json()["workspace"]["draft_object_key"] == key
