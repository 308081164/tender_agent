"""资质目录 Agent：路径校验、扫描、缺口计算。"""
from __future__ import annotations

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
