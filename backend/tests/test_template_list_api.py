"""模板列表 API：新建模板应在向导可选列表中可见且排在前面。"""
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


def _add_template(name: str, enabled: bool = True, kind: str = "template") -> None:
    db = TestSession()
    try:
        db.add(Template(
            name=name,
            description="测试",
            object_key=f"templates/{name}.docx",
            placeholders={"list": []},
            template_code="common",
            kind=kind,
            enabled=enabled,
        ))
        db.commit()
    finally:
        db.close()


def _clear_templates() -> None:
    db = TestSession()
    try:
        db.query(Template).delete()
        db.commit()
    finally:
        db.close()


def test_list_templates_newest_first_and_enabled_only():
    _clear_templates()
    _add_template("旧模板")
    _add_template("新上传模板")
    _add_template("未启用模板", enabled=False)
    _add_template("招标文件", kind="tender_doc")

    client = TestClient(app)
    res = client.get("/api/templates")
    assert res.status_code == 200
    names = [t["name"] for t in res.json()]
    assert names == ["新上传模板", "旧模板"]
    assert "未启用模板" not in names
    assert "招标文件" not in names


if __name__ == "__main__":
    test_list_templates_newest_first_and_enabled_only()
    print("ok")
