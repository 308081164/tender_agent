"""Agent 中台 API 级集成测试：消息 → 卡片 → 动作回调全链路。

运行方式：
    python -m pytest backend/tests/test_agent_api.py
    或直接：python backend/tests/test_agent_api.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.models import FieldDef, Template
from app.routers import api as api_router

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


def _seed():
    db = TestSession()
    try:
        if not db.query(Template).filter(Template.name == "铁路工程总承包模板").first():
            db.add(Template(
                name="铁路工程总承包模板", description="", object_key="templates/tpl.docx",
                placeholders={"list": ["project_name"]}, template_code="common",
                kind="template", enabled=True,
            ))
        if not db.query(FieldDef).filter(FieldDef.key == "project_name").first():
            db.add(FieldDef(key="project_name", name="项目名称", field_type="文本", required=True, sort_order=1))
        db.commit()
    finally:
        db.close()


def test_chat_project_flow_api():
    _seed()
    client = TestClient(app)

    s = client.post("/api/chat/sessions", json={"title": "写标书"}).json()
    sid = s["id"]

    # 1. 发送消息 → 模板筛选卡
    r = client.post(f"/api/chat/sessions/{sid}/messages", json={"content": "帮我写一份标书"})
    assert r.status_code == 200, r.text
    data = r.json()
    cards = data["assistant_message"]["metadata"].get("cards") or []
    assert cards and cards[0]["type"] == "template_picker"
    picker_card = cards[0]
    tpl_id = picker_card["payload"]["templates"][0]["id"]

    # 2. 点选模板 → 字段收集卡，原卡片固化
    r = client.post(f"/api/chat/sessions/{sid}/actions", json={
        "message_id": data["assistant_message"]["id"],
        "card_id": picker_card["id"],
        "action": "select_template",
        "payload": {"template_id": tpl_id},
    })
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["user_message"]["content"].startswith("选择模板")
    assert data["acted_message"]["metadata"]["cards"][0]["state"] == "confirmed"
    collect_card = data["assistant_message"]["metadata"]["cards"][0]
    assert collect_card["type"] == "field_collect"

    # 3. 确认字段 → 项目创建 + 初稿生成
    with patch("app.services.agent_flows.document_agent.generate_document_from_template",
               return_value=(b"gen", {"generated_keys": ["project_name"]})), \
         patch("app.services.agent_flows.storage.download_bytes", return_value=b"tpl"), \
         patch("app.services.agent_flows.storage.upload_bytes", side_effect=lambda k, d, c: k):
        r = client.post(f"/api/chat/sessions/{sid}/actions", json={
            "message_id": data["assistant_message"]["id"],
            "card_id": collect_card["id"],
            "action": "confirm_fields",
            "payload": {"fields": {"project_name": "京沪高铁维保标段"}},
        })
    assert r.status_code == 200, r.text
    data = r.json()
    card = data["assistant_message"]["metadata"]["cards"][0]
    assert card["type"] == "project_info"
    assert card["payload"]["title"] == "京沪高铁维保标段"
    assert data["metadata"].get("workspace_updated") is True

    # 4. 流程结束后可正常对话（不再被状态机拦截）
    r = client.post(f"/api/chat/sessions/{sid}/messages", json={"content": "公司有哪些资质？"})
    assert r.status_code == 200, r.text
    assert r.json()["assistant_message"]["metadata"].get("intent") != "flow_pending"


def test_chat_template_flow_api():
    _seed()
    client = TestClient(app)
    s = client.post("/api/chat/sessions", json={"title": "建模板"}).json()
    sid = s["id"]

    detection = {
        "candidates": [
            {"key": "project_name", "field_name": "项目名称", "original_text": "某某工程",
             "confidence": 0.9, "reason": "AI 识别", "source": "ai"},
        ],
        "existing_placeholders": [],
        "paragraph_count": 5,
        "document_excerpt": "...",
    }
    patches = (
        patch("app.services.agent_tools.storage.download_bytes", return_value=b"docx"),
        patch("app.services.agent_tools.storage.upload_bytes", side_effect=lambda k, d, c: k),
        patch("app.services.agent_tools.storage.delete_object", return_value=None),
        patch("app.services.agent_tools.word.extract_placeholders", return_value=[]),
        patch("app.services.agent_tools.template_detect.detect_placeholder_candidates",
              return_value=detection),
        patch("app.services.agent_tools.template_detect.apply_placeholder_mappings",
              return_value=(b"new", {"project_name": "某某工程"}, ["project_name"])),
    )
    for p in patches:
        p.start()
    try:
        # 模拟工作区已有上传文档
        db = TestSession()
        from app.models import ChatSession
        sess = db.query(ChatSession).filter(ChatSession.id == sid).first()
        sess.workspace = {"template_object_key": "chat/x/doc.docx", "filename": "完整标书.docx"}
        db.commit()
        db.close()

        # 1. 发起创建模板 → 映射确认卡
        r = client.post(f"/api/chat/sessions/{sid}/messages", json={"content": "把这个标书创建为模板"})
        assert r.status_code == 200, r.text
        data = r.json()
        cards = data["assistant_message"]["metadata"].get("cards") or []
        assert cards and cards[0]["type"] == "mapping_confirm"
        map_card = cards[0]

        # 2. 确认映射 → 模板信息卡
        r = client.post(f"/api/chat/sessions/{sid}/actions", json={
            "message_id": data["assistant_message"]["id"],
            "card_id": map_card["id"],
            "action": "confirm_mapping",
            "payload": {"mappings": map_card["payload"]["mappings"]},
        })
        assert r.status_code == 200, r.text
        data = r.json()
        card = data["assistant_message"]["metadata"]["cards"][0]
        assert card["type"] == "template_info"
        assert card["payload"]["placeholder_count"] == 1
        assert data["acted_message"]["metadata"]["cards"][0]["state"] == "confirmed"
    finally:
        for p in patches:
            p.stop()


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(tests)} tests passed")
