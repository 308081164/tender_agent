"""上传只存档，进入创作时把第二步写进已绑定的模板。

这些测试走真实上传、再次选用和 docx 替换，不依赖 Aspose。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.models import CompanyProfile, FieldDef
from app.routers import admin as admin_router
from app.routers import api as api_router
from app.services import storage
from app.services.docx_ooxml import build_docx, build_styled_docx, build_table_docx, document_text

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
Base.metadata.create_all(engine)
TestSession = sessionmaker(bind=engine)
app = FastAPI()
app.include_router(api_router.router, prefix="/api")
app.include_router(admin_router.router, prefix="/api")

_FILES: dict[str, bytes] = {}


def _upload(key, data, content_type="application/octet-stream"):
    _FILES[key] = data
    return key


def _download(key):
    if key not in _FILES:
        raise FileNotFoundError(key)
    return _FILES[key]


storage.upload_bytes = _upload
storage.download_bytes = _download


def _override_get_db():
    db = TestSession()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = _override_get_db
client = TestClient(app)


def setup_module():
    os.environ["TENDER_DISABLE_ASPOSE"] = "1"

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
OLD_PROJECT = "和远智能园区改造工程项目"
NEW_PROJECT = "新城智慧交通工程项目"
OLD_TENDER = "HY-2024-OLD-001"
NEW_TENDER = "NEW-2026-009"
OLD_AMOUNT = "人民币壹佰万元整"
OLD_TENDERER = "某市轨道交通集团"
NEW_TENDERER = "新城轨道建设有限公司"
BLANK_MARKER = "铁路工程投标模板2-空白正文"
FILL_REQUEST = "请你帮我结合我给出的基础信息帮我将这些信息填入标书模板中并在文档工作区帮我打开供我查阅"


def _seed_fields():
    db = TestSession()
    specs = [
        ("project_name", "项目名称", True),
        ("tender_no", "招标编号", True),
        ("tenderer", "招标人", True),
        ("duration", "工期", False),
        ("bid_amount", "报价", False),
        ("bidder_name", "投标人", False),
    ]
    for idx, (key, name, required) in enumerate(specs):
        if db.query(FieldDef).filter(FieldDef.key == key).first():
            continue
        db.add(FieldDef(
            key=key, name=name, field_type="文本", required=required,
            template_code="common", sort_order=idx,
        ))
    if not db.query(CompanyProfile).filter(CompanyProfile.id == 1).first():
        db.add(CompanyProfile(id=1, full_name="和远智能股份有限公司", phone="010-88886666"))
    db.commit()
    db.close()


def _post_docx(path: str, filename: str, payload: bytes, kind: str = "auto"):
    os.environ["TENDER_DISABLE_ASPOSE"] = "1"
    return client.post(
        path,
        params={"kind": kind},
        files={"file": (filename, payload, DOCX)},
    )


def _historical_docx() -> bytes:
    return build_docx([
        f"项目名称：{OLD_PROJECT}",
        f"招标编号：{OLD_TENDER}",
        f"投标报价：{OLD_AMOUNT}",
        "工期：180日历天",
        f"招标人：{OLD_TENDERER}",
    ])


def _blank_docx() -> bytes:
    return build_styled_docx([
        ("投标函", "Heading1"),
        ("", None),
        ("技术方案", "Heading1"),
        ("", None),
        (BLANK_MARKER, None),
    ])


def _project_with_fields(template_id: int, fields: dict, *, advance: bool = True) -> dict:
    created = client.post("/api/projects", json={
        "title": "标书项目 SSH",
        "template_id": template_id,
        "source_type": "template",
    })
    assert created.status_code == 200, created.text
    project = created.json()
    saved = client.post(f"/api/projects/{project['id']}/save", json={
        "fields": fields,
        "current_step": 2,
        "advance": advance,
        "create_snapshot": False,
    })
    assert saved.status_code == 200, saved.text
    return saved.json()


def _bind_and_open(project_id: int) -> dict:
    bound = client.post(f"/api/projects/{project_id}/sessions")
    assert bound.status_code == 200, bound.text
    session_id = bound.json()["session"]["id"]
    opened = client.post(f"/api/projects/{project_id}/workspace/open", json={"guided_intake": True})
    assert opened.status_code == 200, opened.text
    workspace = client.get(f"/api/chat/sessions/{session_id}/workspace")
    assert workspace.status_code == 200, workspace.text
    return {
        "session_id": session_id,
        "opening": opened.json(),
        "workspace": workspace.json(),
    }


def _workspace_text(session_id: int) -> str:
    downloaded = client.get(f"/api/chat/sessions/{session_id}/workspace/download")
    assert downloaded.status_code == 200, downloaded.text
    return document_text(downloaded.content)


def test_historical_docx_replaces_old_facts_after_step3():
    _seed_fields()
    uploaded = _post_docx("/api/templates/upload", "历史标书.docx", _historical_docx(), "history")
    assert uploaded.status_code == 200, uploaded.text
    template_id = uploaded.json()["id"]
    assert uploaded.json()["enabled"] is True
    listed = client.get("/api/templates").json()
    assert any(item["id"] == template_id for item in listed)

    project = _project_with_fields(template_id, {
        "project_name": NEW_PROJECT,
        "tender_no": NEW_TENDER,
        "tenderer": NEW_TENDERER,
        "duration": "180日历天",
    })
    assert project["current_step"] == 3
    opened = _bind_and_open(project["id"])
    text = _workspace_text(opened["session_id"])
    assert OLD_PROJECT not in text
    assert NEW_PROJECT in text
    assert OLD_TENDER not in text
    assert NEW_TENDER in text
    assert OLD_AMOUNT not in text
    assert OLD_TENDERER not in text
    assert NEW_TENDERER in text
    ws = opened["workspace"]["workspace"]
    assert ws.get("draft_object_key") or ws.get("template_object_key")
    ctx = client.get(f"/api/projects/{project['id']}/context")
    assert ctx.status_code == 200, ctx.text
    known = ctx.json()["known_fields"]
    assert known["project_name"] == NEW_PROJECT
    assert known["tenderer"] == NEW_TENDERER
    assert known["duration"] == "180日历天"


def test_blank_template_upload_does_not_require_engineer_page():
    _seed_fields()
    uploaded = _post_docx(
        "/api/admin/templates/upload",
        "空白模板.docx",
        _blank_docx(),
        "skeleton",
    )
    assert uploaded.status_code == 200, uploaded.text
    body = uploaded.json()
    assert body["enabled"] is True
    assert body["kind"] == "skeleton"
    assert "/engineer" not in uploaded.text
    project = _project_with_fields(body["id"], {
        "project_name": "空白起点项目",
        "tenderer": "新城轨道建设有限公司",
        "duration": "6个月",
    })
    opened = _bind_and_open(project["id"])
    greeting = opened["opening"]["assistant_message"]["content"]
    assert "投标函" in greeting
    assert "技术方案" in greeting
    assert "请先在左侧工作区上传模板" not in greeting
    assert "工程化" not in greeting
    assert BLANK_MARKER in _workspace_text(opened["session_id"])
    cards = opened["opening"]["assistant_message"]["metadata"].get("cards") or []
    assert all(card.get("type") != "mapping_confirm" for card in cards)


def test_adhoc_upload_is_listed_for_the_next_project():
    payload = build_docx(["临时模板正文-ADHOC-77", "供下一份标书选用。"])
    uploaded = _post_docx("/api/templates/upload", "临时上传的标书.docx", payload, "auto")
    assert uploaded.status_code == 200, uploaded.text
    template_id = uploaded.json()["id"]
    listed = client.get("/api/templates").json()
    assert any(item["id"] == template_id and "临时上传" in item["name"] for item in listed)
    again = client.post("/api/projects", json={
        "title": "下一份标书",
        "template_id": template_id,
    })
    assert again.status_code == 200, again.text
    assert again.json()["template_id"] == template_id


def test_chat_upload_persists_without_mapping_card():
    payload = build_docx(["对话上传正文", f"项目名称：{OLD_PROJECT}"])
    session = client.post("/api/chat/sessions", json={"title": "上传"}).json()
    uploaded = client.post(
        f"/api/chat/sessions/{session['id']}/upload",
        files={"file": ("对话标书.docx", payload, DOCX)},
    )
    assert uploaded.status_code == 200, uploaded.text
    message = uploaded.json()["assistant_message"]
    cards = (message.get("metadata") or {}).get("cards") or []
    assert all(card.get("type") != "mapping_confirm" for card in cards)
    assert "映射" not in message["content"] or "不必" in message["content"]
    assert "占位符编辑" in message["content"]
    listed = client.get("/api/templates").json()
    assert any("对话标书" in item["name"] for item in listed)
    ws = uploaded.json()["workspace"]
    assert ws.get("draft_object_key") or ws.get("template_object_key")


def test_greeting_skips_filled_step2_fields_and_later_turn_has_no_intake_card(monkeypatch):
    _seed_fields()
    db = TestSession()
    company = db.query(CompanyProfile).filter(CompanyProfile.id == 1).first()
    company.full_name = "和远智能股份有限公司"
    db.commit()
    db.close()
    doc = build_docx([
        "项目名称：已填项目不必再问",
        "招标人：新城轨道建设有限公司",
        "工期：90日历天",
        "投标人：和远智能科技有限公司",
        f"投标报价：{OLD_AMOUNT}",
    ])
    uploaded = _post_docx("/api/templates/upload", "冲突标书.docx", doc, "history")
    assert uploaded.status_code == 200, uploaded.text
    project = _project_with_fields(uploaded.json()["id"], {
        "project_name": "已填项目不必再问",
        "tenderer": "新城轨道建设有限公司",
        "duration": "12个月",
    })
    opened = _bind_and_open(project["id"])
    greeting = opened["opening"]["assistant_message"]["content"]
    assert "已填项目不必再问" in greeting
    assert "新城轨道建设有限公司" in greeting
    assert "12个月" in greeting
    assert "90日历天" in greeting
    assert "报价" in greeting
    assert "和远智能科技有限公司" in greeting
    assert "请填写项目名称" not in greeting
    assert "请填写招标人" not in greeting
    assert "请填写工期" not in greeting
    assert "请先在左侧工作区上传模板" not in greeting
    cards = opened["opening"]["assistant_message"]["metadata"].get("cards") or []
    card_keys = []
    for card in cards:
        for field in (card.get("payload") or {}).get("fields") or []:
            card_keys.append(field.get("key"))
    assert "project_name" not in card_keys
    assert "tenderer" not in card_keys
    assert "duration" not in card_keys

    async def no_semantic(*_args, **_kwargs):
        return None

    async def no_tools(*_args, **_kwargs):
        return {}

    async def weekday(*_args, **_kwargs):
        return "今天是星期四。"

    monkeypatch.setattr("app.services.agent_semantic.process_with_semantic_router", no_semantic)
    monkeypatch.setattr("app.services.agent_tool_loop._chat_with_tools", no_tools)
    monkeypatch.setattr("app.services.ai.chat_completion", weekday)
    follow = client.post(
        f"/api/chat/sessions/{opened['session_id']}/messages",
        json={"content": "今天星期几", "context": {"project_id": project["id"]}},
    )
    assert follow.status_code == 200, follow.text
    answer = follow.json()["assistant_message"]["content"]
    later_cards = follow.json()["assistant_message"]["metadata"].get("cards") or []
    assert "今天是星期四" in answer
    assert all(card.get("type") != "field_collect" for card in later_cards)
    assert "待填基础信息" not in answer
    assert "请先在左侧工作区上传模板" not in answer


def test_bound_template_fill_request_opens_workspace_without_upload_prompt(monkeypatch):
    _seed_fields()
    uploaded = _post_docx(
        "/api/templates/upload",
        "铁路工程投标模板2-空白.docx",
        _blank_docx(),
        "skeleton",
    )
    assert uploaded.status_code == 200, uploaded.text
    project = _project_with_fields(uploaded.json()["id"], {
        "project_name": "SSH示范项目",
        "tenderer": "新城轨道建设有限公司",
        "duration": "12个月",
    })
    # 复现截图：会话只绑了项目，工作区还没有文档键。
    from app.models import ChatSession

    db = TestSession()
    session = ChatSession(
        title="标书项目 SSH",
        workspace={"project_id": project["id"], "guided_intake": True},
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    session_id = session.id
    db.close()

    async def as_generate(*_args, **_kwargs):
        return {
            "answer": "不会用到这条，因为绑定模板后应先交接。",
            "mode": "action",
            "metadata": {"intent": "generate_document"},
        }

    monkeypatch.setattr("app.services.agent_semantic.process_with_semantic_router", as_generate)
    response = client.post(
        f"/api/chat/sessions/{session_id}/messages",
        json={"content": FILL_REQUEST, "context": {"project_id": project["id"]}},
    )
    assert response.status_code == 200, response.text
    answer = response.json()["assistant_message"]["content"]
    assert "请先在左侧工作区上传模板" not in answer
    assert "项目名称 XX" not in answer
    assert "招标人 YY" not in answer
    assert "工期 12 个月" not in answer
    assert "供货范围" not in answer
    assert "交货期" not in answer
    assert "竞标有效期" not in answer
    assert "下一问题" not in answer
    assert "SSH示范项目" in answer
    assert "新城轨道建设有限公司" in answer
    assert "12个月" in answer
    assert "请填写项目名称" not in answer
    assert "请填写招标人" not in answer
    workspace = client.get(f"/api/chat/sessions/{session_id}/workspace")
    assert workspace.status_code == 200, workspace.text
    ws = workspace.json()["workspace"]
    assert ws.get("draft_object_key") or ws.get("template_object_key")
    assert "铁路工程投标模板2-空白" in (ws.get("filename") or "")
    assert BLANK_MARKER in _workspace_text(session_id)
    ctx = client.get(f"/api/projects/{project['id']}/context")
    known = ctx.json()["known_fields"]
    assert known["project_name"] == "SSH示范项目"
    assert known["tenderer"] == "新城轨道建设有限公司"
    assert known["duration"] == "12个月"


def test_table_cells_are_replaced_and_greeting_does_not_claim_leftovers():
    """项目名称、招标编号、金额只在表格单元格里时，下载件必须换成新值。"""
    _seed_fields()
    table = build_table_docx([
        ["项目名称", OLD_PROJECT],
        ["招标编号", OLD_TENDER],
        ["投标报价", OLD_AMOUNT],
    ])
    uploaded = _post_docx("/api/templates/upload", "表格历史标书.docx", table, "history")
    assert uploaded.status_code == 200, uploaded.text
    project = _project_with_fields(uploaded.json()["id"], {
        "project_name": NEW_PROJECT,
        "tender_no": NEW_TENDER,
        "tenderer": NEW_TENDERER,
        "duration": "180日历天",
        "bid_amount": "人民币贰佰万元整",
    })
    opened = _bind_and_open(project["id"])
    text = _workspace_text(opened["session_id"])
    greeting = opened["opening"]["assistant_message"]["content"]
    assert NEW_PROJECT in text
    assert NEW_TENDER in text
    assert "人民币贰佰万元整" in text
    assert OLD_PROJECT not in text
    assert OLD_TENDER not in text
    assert OLD_AMOUNT not in text
    if any(old in text for old in (OLD_PROJECT, OLD_TENDER, OLD_AMOUNT)):
        assert "已写入草稿" not in greeting
    assert "已写入草稿" in greeting


def test_project_name_without_suffix_is_replaced():
    _seed_fields()
    old_name = "南山医院迁建"
    new_name = "湾区配套迁建"
    doc = build_docx([
        f"项目名称：{old_name}",
        f"招标编号：{OLD_TENDER}",
    ])
    uploaded = _post_docx("/api/templates/upload", "无后缀项目名.docx", doc, "history")
    assert uploaded.status_code == 200, uploaded.text
    project = _project_with_fields(uploaded.json()["id"], {
        "project_name": new_name,
        "tender_no": NEW_TENDER,
        "tenderer": NEW_TENDERER,
        "duration": "90日历天",
    })
    opened = _bind_and_open(project["id"])
    text = _workspace_text(opened["session_id"])
    assert old_name not in text
    assert new_name in text
    assert OLD_TENDER not in text
    assert NEW_TENDER in text


def test_confirm_price_writes_into_the_draft_immediately():
    _seed_fields()
    uploaded = _post_docx("/api/templates/upload", "待报价.docx", _historical_docx(), "history")
    assert uploaded.status_code == 200, uploaded.text
    project = _project_with_fields(uploaded.json()["id"], {
        "project_name": NEW_PROJECT,
        "tender_no": NEW_TENDER,
        "tenderer": NEW_TENDERER,
        "duration": "180日历天",
    })
    opened = _bind_and_open(project["id"])
    message = opened["opening"]["assistant_message"]
    new_amount = "人民币贰佰万元整"
    confirmed = client.post(
        f"/api/chat/sessions/{opened['session_id']}/actions",
        json={
            "message_id": message["id"],
            "card_id": "creation-open-decisions",
            "action": "confirm_fields",
            "payload": {"fields": {"bid_amount": new_amount}},
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    text = _workspace_text(opened["session_id"])
    assert new_amount in text
    assert OLD_AMOUNT not in text


def test_blank_sections_are_started_in_the_downloaded_docx():
    _seed_fields()
    uploaded = _post_docx("/api/templates/upload", "空白起稿.docx", _blank_docx(), "skeleton")
    assert uploaded.status_code == 200, uploaded.text
    project = _project_with_fields(uploaded.json()["id"], {
        "project_name": "空白起点项目",
        "tenderer": NEW_TENDERER,
        "duration": "6个月",
    })
    opened = _bind_and_open(project["id"])
    greeting = opened["opening"]["assistant_message"]["content"]
    text = _workspace_text(opened["session_id"])
    assert "投标函" in greeting
    assert "技术方案" in greeting
    assert "我方参加「空白起点项目」投标，现提交投标函" in text
    assert "技术方案从实施范围、质量措施和进度安排写起" in text
    assert BLANK_MARKER in text
