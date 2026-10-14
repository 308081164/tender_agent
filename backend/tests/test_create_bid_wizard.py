"""新建标书：创建后进入「选择起点」，并绑定项目会话。

向导在 `/projects/:id/step/1` 会调用 POST /projects/:id/sessions。
响应是 `{session, project_id}`。工作目录不合法时必须返回 400，不能变成未处理异常。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from unittest.mock import MagicMock

for _name in ("aspose", "aspose.words"):
    sys.modules.setdefault(_name, MagicMock())

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.models import Template
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
client = TestClient(app)
client_http = TestClient(app, raise_server_exceptions=False)


def _template_id() -> int:
    db = TestSession()
    tpl = Template(
        name="工程化模板",
        object_key="templates/demo.docx",
        placeholders={"list": []},
        kind="template",
        enabled=True,
    )
    db.add(tpl)
    db.commit()
    db.refresh(tpl)
    tid = tpl.id
    db.close()
    return tid


def test_create_bid_lands_on_step1_and_session_id_is_nested():
    created = client.post("/api/projects", json={
        "title": "新建标书",
        "template_id": _template_id(),
        "source_type": "template",
    })
    assert created.status_code == 200, created.text
    project = created.json()
    assert project["current_step"] == 1
    assert project["template_id"]

    bound = client.post(f"/api/projects/{project['id']}/sessions")
    assert bound.status_code == 200, bound.text
    body = bound.json()
    assert body["project_id"] == project["id"]
    session_id = body["session"]["id"]
    assert isinstance(session_id, int)
    assert "id" not in body

    loaded = client.get(f"/api/chat/sessions/{session_id}")
    assert loaded.status_code == 200
    assert loaded.json()["id"] == session_id
    assert loaded.json()["workspace"]["project_id"] == project["id"]

    missing = client_http.get("/api/chat/sessions/undefined")
    assert missing.status_code == 422


def test_create_project_rejects_missing_workspace_dir():
    res = client_http.post("/api/projects", json={
        "title": "新建标书",
        "workspace_dir": "/no/such/bid-folder",
    })
    assert res.status_code == 400
    detail = res.json()["detail"]
    assert isinstance(detail, str)
    assert "路径" in detail or "文件夹" in detail
