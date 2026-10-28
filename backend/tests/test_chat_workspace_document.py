"""文档工作区预览、下载与完整标书合成回归。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ["TENDER_DISABLE_ASPOSE"] = "1"

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
from app.services.docx_ooxml import build_styled_docx, document_text

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

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _override_get_db():
    db = TestSession()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = _override_get_db
client = TestClient(app)


def _seed():
    db = TestSession()
    for key, name in [
        ("project_name", "项目名称"),
        ("tender_no", "招标编号"),
        ("tenderer", "招标人"),
        ("duration", "工期"),
        ("bid_amount", "报价"),
        ("bidder_name", "投标人"),
        ("project_manager", "项目经理"),
    ]:
        if not db.query(FieldDef).filter(FieldDef.key == key).first():
            db.add(FieldDef(key=key, name=name, field_type="文本", required=False, template_code="common"))
    if not db.query(CompanyProfile).filter(CompanyProfile.id == 1).first():
        db.add(CompanyProfile(
            id=1,
            full_name="华远智通科技有限公司",
            intro="华远智通科技有限公司专注于轨道交通智能化运维与机电维保服务。",
        ))
    db.commit()
    db.close()


def _railway_blank_docx() -> bytes:
    return build_styled_docx([
        ("投标函", "Heading1"),
        ("", None),
        ("技术方案", "Heading1"),
        ("", None),
        ("商务标与报价说明", "Heading1"),
        ("", None),
        ("投标人简介", "Heading1"),
        ("", None),
        ("人员配置与工期", "Heading1"),
        ("", None),
        ("资质与业绩", "Heading1"),
        ("", None),
        ("铁路工程投标模板2-空白正文", None),
    ])


def _project(template_id: int) -> dict:
    created = client.post("/api/projects", json={
        "title": "新城智慧交通维保系统投标",
        "template_id": template_id,
        "source_type": "template",
    })
    assert created.status_code == 200
    pid = created.json()["id"]
    saved = client.post(f"/api/projects/{pid}/save", json={
        "fields": {
            "project_name": "新城智慧交通维保系统投标",
            "tenderer": "新城轨道建设有限公司",
            "tender_no": "XC-2026-001",
            "duration": "12个月",
            "bid_amount": "人民币壹佰贰拾万元整",
            "bidder_name": "华远智通科技有限公司",
            "project_manager": "张明",
        },
        "current_step": 3,
        "advance": True,
        "create_snapshot": False,
    })
    assert saved.status_code == 200
    return saved.json()


def test_workspace_preview_and_download_non_empty(monkeypatch):
    _seed()
    monkeypatch.setenv("ONLYOFFICE_ENABLED", "false")
    uploaded = client.post(
        "/api/templates/upload",
        params={"kind": "skeleton"},
        files={"file": ("铁路工程投标模板2-空白.docx", _railway_blank_docx(), DOCX)},
    )
    assert uploaded.status_code == 200
    project = _project(uploaded.json()["id"])
    bound = client.post(f"/api/projects/{project['id']}/sessions")
    session_id = bound.json()["session"]["id"]
    compose = client.post(f"/api/projects/{project['id']}/compose-full-bid", json={
        "requirements": "华远智通科技有限公司投标新城智慧交通维保系统，各章节需完整正文。",
    })
    assert compose.status_code == 200, compose.text

    ws = client.get(f"/api/chat/sessions/{session_id}/workspace")
    assert ws.status_code == 200
    body = ws.json()
    assert body.get("doc_size", 0) > 500
    assert len(body.get("paragraphs") or []) >= 5
    assert body["preview_fallback"]["paragraph_count"] >= 5

    pdf = client.get(f"/api/chat/sessions/{session_id}/workspace/preview.pdf")
    assert pdf.status_code in (200, 503)
    if pdf.status_code == 200:
        assert len(pdf.content) > 100
        assert pdf.headers.get("content-type", "").startswith("application/pdf")

    downloaded = client.get(f"/api/chat/sessions/{session_id}/workspace/download")
    assert downloaded.status_code == 200
    assert len(downloaded.content) > 800
    text = document_text(downloaded.content)
    assert "新城智慧交通维保系统投标" in text
    assert "华远智通科技有限公司" in text
    assert "{{" not in text
    assert text.count("投标函") >= 1
    assert text.count("技术方案") >= 1
    assert len(text) > 2400


def test_compose_full_bid_section_thresholds():
    _seed()
    uploaded = client.post(
        "/api/templates/upload",
        params={"kind": "skeleton"},
        files={"file": ("铁路工程投标模板2-空白.docx", _railway_blank_docx(), DOCX)},
    )
    project = _project(uploaded.json()["id"])
    res = client.post(f"/api/projects/{project['id']}/compose-full-bid", json={})
    assert res.status_code == 200
    meta = res.json()["report"]["meta"]
    assert meta["filled_sections"] >= 5
    assert meta["text_length"] > 2400
    assert meta["placeholders_left"] == 0
