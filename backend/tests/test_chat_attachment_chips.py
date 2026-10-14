"""用户消息上的资料芯片只保存展示字段。"""
from __future__ import annotations

import json
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


def _session_id(client: TestClient) -> int:
    created = client.post("/api/chat/sessions", json={"title": "chips"})
    assert created.status_code == 200
    return created.json()["id"]


def test_message_stores_attachment_chips_without_paths():
    client = TestClient(app)
    sid = _session_id(client)
    res = client.post(
        f"/api/chat/sessions/{sid}/messages",
        json={
            "content": "帮我看一下报价",
            "context": {
                "attachments": [
                    {"name": "报价.png", "kind": "file", "type": "PNG", "path": "/secret/报价.png"},
                    {"name": "", "kind": "file"},
                ],
                "web_search": False,
            },
        },
    )
    assert res.status_code == 200
    user = res.json()["user_message"]
    assert user["content"] == "帮我看一下报价"
    assert user["metadata"]["attachments"] == [{"name": "报价.png", "kind": "file", "type": "PNG"}]
    assert "path" not in user["metadata"]["attachments"][0]

    loaded = client.get(f"/api/chat/sessions/{sid}")
    assert loaded.json()["messages"][0]["metadata"]["attachments"][0]["name"] == "报价.png"


def test_attachment_only_turn_skips_assistant():
    client = TestClient(app)
    sid = _session_id(client)
    res = client.post(
        f"/api/chat/sessions/{sid}/messages",
        json={"content": "  ", "context": {"attachments": [{"name": "执照.pdf", "kind": "file"}]}},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["assistant_message"] is None
    assert body["user_message"]["content"] == ""
    assert body["user_message"]["metadata"]["attachments"][0]["type"] == "PDF"


def test_empty_message_without_chips_is_rejected():
    client = TestClient(app)
    sid = _session_id(client)
    res = client.post(f"/api/chat/sessions/{sid}/messages", json={"content": "   "})
    assert res.status_code == 400


def test_stream_attachment_only_returns_done_without_tokens():
    client = TestClient(app)
    sid = _session_id(client)
    with client.stream(
        "POST",
        f"/api/chat/sessions/{sid}/messages/stream",
        json={"content": "", "context": {"attachments": [{"name": "材料.docx", "kind": "folder"}]}},
    ) as resp:
        assert resp.status_code == 200
        raw = "".join(resp.iter_text())
    assert "token" not in raw
    data = json.loads(raw.strip().removeprefix("data:").strip())
    assert data["type"] == "done"
    chip = data["payload"]["user_message"]["metadata"]["attachments"][0]
    assert chip == {"name": "材料.docx", "kind": "folder", "type": "文件夹"}
    assert data["payload"]["assistant_message"] is None
