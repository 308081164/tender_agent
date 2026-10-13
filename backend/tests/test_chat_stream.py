"""聊天 SSE 流式端点 smoke。"""
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


def test_chat_message_stream_returns_done_event():
    client = TestClient(app)
    s = client.post("/api/chat/sessions", json={"title": "stream-test"})
    assert s.status_code == 200
    sid = s.json()["id"]
    with client.stream(
        "POST",
        f"/api/chat/sessions/{sid}/messages/stream",
        json={"content": "你好"},
    ) as resp:
        assert resp.status_code == 200
        buf = ""
        saw_done = False
        for chunk in resp.iter_text():
            buf += chunk
            while "\n\n" in buf:
                part, buf = buf.split("\n\n", 1)
                if not part.strip().startswith("data:"):
                    continue
                data = json.loads(part.strip()[5:])
                if data.get("type") == "done":
                    saw_done = True
                    assert data["payload"].get("assistant_message")
        assert saw_done
