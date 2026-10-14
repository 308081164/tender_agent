"""项目草稿预览路由已随创作工作台移除；项目会话开场仍可绑定。"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.models import FieldDef, Template, TenderProject
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


def _seed_project() -> int:
    db = TestSession()
    try:
        tpl = Template(
            name="测试模板",
            description="",
            object_key="templates/t.docx",
            placeholders={"list": ["project_name"]},
            template_code="common",
            kind="template",
            enabled=True,
        )
        db.add(tpl)
        db.flush()
        if not db.query(FieldDef).filter(FieldDef.key == "project_name").first():
            db.add(FieldDef(key="project_name", name="项目名称", field_type="文本", required=True, sort_order=1))
        p = TenderProject(title="测试项目", template_id=tpl.id, fields={}, current_step=2)
        db.add(p)
        db.commit()
        db.refresh(p)
        return p.id
    finally:
        db.close()


def test_workspace_draft_preview_routes_removed():
    """创作工作台的草稿 PDF 预览会因 docx_bytes 未定义而失败，路由应一并删除。"""
    pid = _seed_project()
    client = TestClient(app)
    for path in (
        f"/api/projects/{pid}/draft-preview.pdf",
        f"/api/projects/{pid}/draft-preview/status",
        f"/api/projects/{pid}/draft-preview/jobs/missing",
    ):
        response = client.get(path)
        assert response.status_code == 404, response.text
    started = client.post(f"/api/projects/{pid}/draft-preview/async")
    assert started.status_code == 404, started.text


def test_workspace_open_creates_assistant_message():
    pid = _seed_project()
    client = TestClient(app)

    with patch(
        "app.services.agent_tools.list_missing_intake_questions",
        new=AsyncMock(return_value={"questions": [], "field_cards": []}),
    ):
        r1 = client.post(f"/api/projects/{pid}/workspace/open", json={"guided_intake": True})
        r2 = client.post(f"/api/projects/{pid}/workspace/open", json={"guided_intake": True})
    assert r1.status_code == 200, r1.text
    assert r1.json()["created"] is True
    assert r1.json()["assistant_message"]["metadata"]["kind"] == "workspace_opening"
    assert r2.json()["created"] is False
