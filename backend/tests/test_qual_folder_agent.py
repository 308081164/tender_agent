"""资质目录 Agent：路径校验、扫描、缺口计算。"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

import pytest

from app.models import CompanyProfile, FieldDef
from app.services.agent_qual_folder import (
    PathNotAllowedError,
    extract_folder_path_from_text,
    get_onboarding_gaps,
    is_qual_folder_intent,
    normalize_folder_path,
    scan_qual_folder,
    apply_company_field_patch,
    classify_folder_materials,
    _rule_classify_material,
    import_qual_folder_pipeline,
)
from app.database import SessionLocal, engine, Base


def _fresh_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    return SessionLocal()


def test_extract_path_from_message():
    text = '请扫描资质文件夹 C:\\Users\\test\\Desktop\\资质包'
    assert extract_folder_path_from_text(text) == 'C:\\Users\\test\\Desktop\\资质包'
    assert is_qual_folder_intent(text) is True


def test_path_rejects_parent_traversal(tmp_path):
    bad = str(tmp_path / ".." / "etc")
    with pytest.raises(PathNotAllowedError):
        normalize_folder_path(bad)


def test_scan_folder_mock_files(tmp_path, monkeypatch):
    folder = tmp_path / "quals"
    folder.mkdir()
    (folder / "a.pdf").write_bytes(b"%PDF-1.4 mock")
    (folder / "b.txt").write_text("营业执照 测试公司", encoding="utf-8")
    (folder / "skip.exe").write_bytes(b"bin")

    monkeypatch.setattr(
        "app.services.agent_qual_folder.allowed_path_prefixes",
        lambda: [tmp_path.resolve()],
    )
    root = normalize_folder_path(str(folder))
    result = scan_qual_folder(root)
    assert result["file_count"] == 2
    names = {f["name"] for f in result["files"]}
    assert names == {"a.pdf", "b.txt"}


def test_onboarding_gaps_empty_company():
    db = _fresh_db()
    db.query(CompanyProfile).delete()
    db.query(FieldDef).delete()
    db.add(CompanyProfile(id=1, full_name=""))
    db.add(FieldDef(
        name="投标人", key="bidder_name", field_type="文本",
        is_company_default=True, company_field="full_name",
    ))
    db.commit()
    gaps = get_onboarding_gaps(db)
    assert gaps["gap_count"] >= 1
    keys = {g["key"] for g in gaps["gaps"]}
    assert "full_name" in keys
    assert any(g["url"].startswith("/admin/") for g in gaps["gaps"])
    db.close()


def test_rule_classify_by_content_not_folder_name(tmp_path):
    """无固定目录：乱序路径下仍按正文识别营业执照。"""
    material = {
        "file_id": 0,
        "path": str(tmp_path / "x/y/z/random_scan001.pdf"),
        "name": "random_scan001.pdf",
        "relative_path": "x/y/z/random_scan001.pdf",
        "text": "营业执照 统一社会信用代码 91310000MA1K123456",
    }
    out = _rule_classify_material(material)
    assert out["doc_type"] == "business_license"
    assert out["confidence"] >= 0.65


@pytest.mark.asyncio
async def test_llm_classify_folder_materials_mock(monkeypatch):
    monkeypatch.setattr("app.services.ai.is_multimodal_ready", lambda db=None: True)
    materials = [
        {
            "file_id": 0,
            "path": "/tmp/a.pdf",
            "name": "a.pdf",
            "extension": "pdf",
            "relative_path": "nested/weird/a.pdf",
            "text": "基本存款账户信息 开户银行 某某支行",
        },
    ]

    async def fake_chat(messages, db=None, provider=None, task_kind="text"):
        return json.dumps([{
            "file_id": 0,
            "doc_type": "bank_account_proof",
            "confidence": 0.88,
            "needs_verify": False,
            "company_field_hints": ["bank_name", "bank_account"],
            "reasoning": "正文含基本存款账户与开户银行",
        }])

    monkeypatch.setattr("app.services.ai.chat_completion", fake_chat)
    rows = await classify_folder_materials(materials, db=None)
    assert len(rows) == 1
    assert rows[0]["doc_type"] == "bank_account_proof"
    assert rows[0]["confidence"] == 0.88
    assert rows[0]["needs_verify"] is False


@pytest.mark.asyncio
async def test_import_pipeline_exploration_dry_run(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.ai.is_multimodal_ready", lambda db=None: True)
    folder = tmp_path / "flat"
    folder.mkdir()
    (folder / "doc1.txt").write_text("业绩合同 某某项目中标", encoding="utf-8")

    monkeypatch.setattr(
        "app.services.agent_qual_folder.allowed_path_prefixes",
        lambda: [tmp_path.resolve()],
    )

    async def fake_classify(materials, db=None):
        return [{
            "file_id": 0,
            "path": materials[0]["path"],
            "name": materials[0]["name"],
            "relative_path": materials[0]["relative_path"],
            "doc_type": "performance_proof",
            "doc_type_label": "业绩证明",
            "confidence": 0.9,
            "needs_verify": False,
            "company_field_hints": [],
            "reasoning": "mock",
            "source": "ai",
        }]

    monkeypatch.setattr(
        "app.services.agent_qual_folder.classify_folder_materials",
        fake_classify,
    )

    monkeypatch.setattr(
        "app.services.ai.is_multimodal_ready",
        lambda _db: True,
    )

    db = _fresh_db()
    result = await import_qual_folder_pipeline(db, str(folder), dry_run=True)
    assert result["exploration"]["classified_count"] == 1
    assert result["qualifications_created"][0]["exploration"]["doc_type"] == "performance_proof"
    db.close()


def test_sensitive_company_patch_suggestion():
    db = _fresh_db()
    db.query(CompanyProfile).delete()
    db.add(CompanyProfile(id=1, bank_account="622200011111"))
    db.commit()
    out = apply_company_field_patch(db, {"bank_account": "622200099999"})
    assert out["applied"] == []
    assert len(out["suggestions"]) == 1
    assert out["suggestions"][0]["key"] == "bank_account"
    db.close()
